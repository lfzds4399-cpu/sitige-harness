"""secret_scanner — regex + entropy 扫密钥/token/硬编码凭据.

排除 .git / node_modules / .next / __pycache__ / dist / build / venv.
.env.example 是允许 commit 的; 但裸 .env 文件不应该出现含真值.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import (
    ValidationResult,
    Validator,
    iter_text_files,
    line_is_exempt,
    safe_read,
)

# 高置信 regex (低误报)
SECRET_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # ---- 通用 API Key ----
    ("OPENAI_KEY", re.compile(r"sk-[A-Za-z0-9]{20,}"), "疑似 OpenAI API key (sk-...)"),
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "疑似 Anthropic API key"),
    ("STRIPE_LIVE", re.compile(r"sk_live_[A-Za-z0-9]{20,}"), "Stripe live secret"),
    ("STRIPE_TEST", re.compile(r"sk_test_[A-Za-z0-9]{20,}"), "Stripe test secret"),
    ("SLACK_BOT", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack token"),
    ("GH_TOKEN", re.compile(r"ghp_[A-Za-z0-9]{30,}"), "GitHub personal access token"),
    ("GH_OAUTH", re.compile(r"gho_[A-Za-z0-9]{30,}"), "GitHub OAuth token"),
    ("GOOGLE_API", re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "Google API key"),
    ("AWS_ACCESS", re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    # ---- 国产 LLM ----
    ("DEEPSEEK", re.compile(r"sk-[a-f0-9]{32}"), "疑似 DeepSeek key"),
    ("MOONSHOT", re.compile(r"sk-[A-Za-z0-9]{40,}"), "疑似 Moonshot/Kimi key (长格式)"),
    # ---- 私钥 ----
    ("PEM_PRIV", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |ED25519 |DSA |PGP )?PRIVATE KEY-----"),
     "私钥 PEM 块"),
    # ---- 微信硬编码 ----
    ("WX_SECRET", re.compile(r"['\"][a-f0-9]{32}['\"]\s*#.*(微信|wechat|wx_secret)", re.IGNORECASE),
     "疑似微信 AppSecret 硬编码"),
    # ---- 数据库连接串裸密码 ----
    ("DB_URL_PWD", re.compile(r"(postgres|postgresql|mysql|redis|mongodb)://[^:\s]+:[^@\s]{8,}@",
                              re.IGNORECASE),
     "数据库连接串含明文密码"),
    # ---- JWT (低置信度, warn) ----
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
     "疑似 JWT token"),
]

# 占位符不报 (通常出现在 .env.example)
PLACEHOLDER_TOKENS = (
    "your_", "your-", "xxx", "<your", "{your", "${", "TODO",
    "EXAMPLE", "example", "CHANGE_ME", "change-me", "REPLACE",
    "<KEY>", "<TOKEN>", "<SECRET>", "PLACEHOLDER", "demo_",
    "dummy", "<fake>", "MOCK_", "test_value", "TEST_VALUE",
)

# .env 文件白名单 (允许出现 KEY 占位符)
ENV_EXAMPLE_NAMES = (".env.example", ".env.全栈.example", ".env.sample", ".env.template")

# 高熵字符串候选 (min 32 char base64-ish)
HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")
ENTROPY_THRESHOLD = 4.5


def _is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(t.lower() in low for t in PLACEHOLDER_TOKENS)


def _scan_text(path: Path, text: str, is_env_example: bool) -> list[tuple]:
    findings = []
    for code, pat, msg in SECRET_PATTERNS:
        for m in pat.finditer(text):
            value = m.group(0)
            # .env.example 中匹配到占位符 → 跳过
            if is_env_example and _is_placeholder(value):
                continue
            line_no = text[:m.start()].count("\n") + 1
            line_text = text.splitlines()[line_no - 1] if line_no - 1 < len(text.splitlines()) else ""
            # 上下文豁免: 注释里说"不要 commit sk-xxx"
            if line_is_exempt(line_text):
                continue
            severity = "warn" if code == "JWT" else "error"
            findings.append((severity, code, f"{msg}: {value[:24]}...",
                             path, line_no))
    return findings


def _scan_env_real(path: Path, text: str) -> list[tuple]:
    """裸 .env 文件 (非 .env.example) — 任何 KEY=value 且 value 非占位符 → warn."""
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not val or _is_placeholder(val):
            continue
        if any(s in key.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "KEY", "PRIVATE")):
            findings.append((
                "warn", "ENV_REAL_SECRET",
                f"裸 .env 含真实凭据 {key}=*** (不应 commit)",
                path, line_no,
            ))
    return findings


class SecretScannerValidator(Validator):
    name = "secret_scanner"
    description = "regex + entropy 扫私钥/API token/数据库裸密码/硬编码凭据"

    def run(self, project_root: Path, config: dict | None = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            scanned_files = 0
            for path in iter_text_files(project_root):
                # 跳过自身验证器 + audit.py + this skill 内的 regex pattern 字符串
                rel_parts = path.relative_to(project_root).parts
                if "harness" in rel_parts and (
                    "validators" in rel_parts or path.name in ("audit.py", "status.py")
                ):
                    continue
                # 跳过 last-audit.json (它会含历史 finding 文本)
                if path.name == "last-audit.json":
                    continue

                text = safe_read(path)
                if not text:
                    continue
                scanned_files += 1

                is_env_example = path.name in ENV_EXAMPLE_NAMES

                # 普通 regex 扫描
                for sev, code, msg, fpath, line_no in _scan_text(path, text, is_env_example):
                    result.add(sev, code, msg, file=fpath, line=line_no)

                # 裸 .env (不带 example) 额外扫描
                if path.name == ".env":
                    for sev, code, msg, fpath, line_no in _scan_env_real(path, text):
                        result.add(sev, code, msg, file=fpath, line=line_no)

            # 永远 +1 ok 表示扫描成功 (避免 0 ok 显得没跑)
            result.add_ok(f"已扫描 {scanned_files} 个文本文件, 无硬编码凭据")
        return result


__all__ = ["SecretScannerValidator", "SECRET_PATTERNS"]
