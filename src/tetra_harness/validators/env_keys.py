"""env_keys — 必填 env key 检查.

读 .env.全栈.example 提取所有 🔴 标记的必填 key, 检查 .env 是否存在 + 必填是否填了真值.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import Validator, ValidationResult, safe_read


# 🔴 标记 = 必填 (用户对约定: 8 项必填)
REQUIRED_MARKER_PATTERNS = (
    re.compile(r"#.*🔴.*$"),
    re.compile(r"#.*必填.*$"),
    re.compile(r"#.*REQUIRED.*$", re.IGNORECASE),
)

PLACEHOLDER_VALUES = (
    "your_", "your-", "xxx", "<your", "{your", "${",
    "TODO", "EXAMPLE", "example", "CHANGE_ME", "REPLACE",
    "<KEY>", "<TOKEN>", "<SECRET>", "PLACEHOLDER",
    "demo", "dummy", "<fake>", "MOCK_",
    "sk-xxx", "sk-yyy",
)


def _extract_required_keys(env_example_text: str) -> list[tuple[str, int]]:
    """提取被标 🔴 / 必填 的 KEY (前一行 / 同行注释)."""
    keys = []
    lines = env_example_text.splitlines()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        if "=" not in line_stripped:
            continue
        key = line_stripped.split("=", 1)[0].strip()
        if not key or not re.match(r"^[A-Z][A-Z0-9_]*$", key):
            continue

        # 同行注释含 🔴/必填
        if any(p.search(line) for p in REQUIRED_MARKER_PATTERNS):
            keys.append((key, i + 1))
            continue
        # 上一行注释含 🔴/必填
        if i > 0 and any(p.search(lines[i - 1]) for p in REQUIRED_MARKER_PATTERNS):
            keys.append((key, i + 1))
    return keys


def _is_placeholder(val: str) -> bool:
    if not val:
        return True
    val = val.strip().strip('"').strip("'")
    if not val:
        return True
    low = val.lower()
    return any(t.lower() in low for t in PLACEHOLDER_VALUES if t)


def _parse_env_kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class EnvKeysValidator(Validator):
    name = "env_keys"
    description = "必填 env key 检查 (基于 .env.全栈.example 中 🔴 标记)"

    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            example_path = project_root / ".env.全栈.example"
            if not example_path.is_file():
                # fallback to .env.example
                example_path = project_root / ".env.example"
            if not example_path.is_file():
                result.add("warn", "ENV_EXAMPLE_MISSING",
                           "未找到 .env.全栈.example 或 .env.example, 跳过检查")
                return result

            example_text = safe_read(example_path)
            required = _extract_required_keys(example_text)

            if not required:
                result.add("info", "NO_REQUIRED_MARKED",
                           f"{example_path.name} 中未发现 🔴/必填 标记 (无强制项)")

            real_env = project_root / ".env"
            if not real_env.is_file():
                # 没有 .env, 提示填
                if required:
                    result.add(
                        "warn", "ENV_FILE_MISSING",
                        f".env 不存在; 需基于 {example_path.name} 创建并填 {len(required)} 必填项",
                        file=example_path,
                    )
                else:
                    result.add_ok(".env.example 健康, 无 .env 但也无强制项")
                return result

            real_kv = _parse_env_kv(safe_read(real_env))
            for key, line_no in required:
                val = real_kv.get(key)
                if val is None:
                    result.add("warn", "ENV_KEY_MISSING",
                               f"必填 KEY '{key}' 未在 .env 中出现",
                               file=real_env, line=line_no)
                elif _is_placeholder(val):
                    result.add("warn", "ENV_KEY_PLACEHOLDER",
                               f"必填 KEY '{key}' 仍是占位符 '{val[:20]}'",
                               file=real_env)
                else:
                    result.add_ok(f"必填 KEY '{key}' 已配置")
        return result


__all__ = ["EnvKeysValidator"]
