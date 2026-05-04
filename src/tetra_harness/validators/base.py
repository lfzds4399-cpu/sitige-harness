"""Validator 抽象基类 + 通用数据模型.

所有 validator 都返回 ValidationResult, finding 含 severity/code/message/file/line.
SKILL E5 上下文豁免: 含 "禁止/禁用/不准/避免/严禁/不要/不说/不出现" 的行不被红线词命中.
"""
from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional

Severity = Literal["info", "warn", "error"]

# SKILL E5: 上下文豁免词 — 这些词所在行的红线词不报错
EXEMPT_CONTEXT_TOKENS: tuple[str, ...] = (
    "禁止", "禁用", "不准", "避免", "严禁", "不要", "不说",
    "不出现", "禁词", "红线", "替代", "改用", "不许",
    "L1_WORDS", "forbidden", "BANNED", "blacklist", "黑名单",
    "举报", "不得", "排除",
)


@dataclass
class Finding:
    severity: Severity
    code: str  # e.g. "MISSING_FILE" / "BANNED_WORD" / "WEAK_PRICE"
    message: str
    file: Optional[Path] = None
    line: Optional[int] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "file": str(self.file) if self.file else None,
            "line": self.line,
            "detail": self.detail,
        }


@dataclass
class ValidationResult:
    validator: str
    ok_count: int = 0
    warn_count: int = 0
    error_count: int = 0
    findings: list[Finding] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    @property
    def total(self) -> int:
        return self.ok_count + self.warn_count + self.error_count

    def add_ok(self, message: str = "") -> None:
        self.ok_count += 1
        # ok 不进 findings, 节省内存. 仅 verbose 模式下另行渲染.

    def add(self, severity: Severity, code: str, message: str, *,
            file: Optional[Path] = None, line: Optional[int] = None,
            detail: str = "") -> None:
        if severity == "info":
            # info 进 findings 但不计入 ok/warn/error
            self.findings.append(Finding(severity, code, message, file, line, detail))
            return
        f = Finding(severity, code, message, file, line, detail)
        self.findings.append(f)
        if severity == "warn":
            self.warn_count += 1
        elif severity == "error":
            self.error_count += 1

    def to_dict(self) -> dict:
        return {
            "validator": self.validator,
            "ok_count": self.ok_count,
            "warn_count": self.warn_count,
            "error_count": self.error_count,
            "elapsed_ms": self.elapsed_ms,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
        }


class Validator(ABC):
    """所有 validator 抽象基类."""

    name: str = "base"
    description: str = ""

    @abstractmethod
    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        """跑验证. project_root 是仓库根, config 来自 configs/audit.yaml."""
        ...

    # ---- 公用 helper ----
    @contextmanager
    def _timed(self, result: ValidationResult) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            result.elapsed_ms = (time.perf_counter() - t0) * 1000


# ---- 模块级公用工具 (单 validator 不重复造轮子) ----
def line_is_exempt(line: str, extra_tokens: Iterable[str] = ()) -> bool:
    """判断一行是否处于"上下文豁免"上下文 (SKILL E5)."""
    tokens = list(EXEMPT_CONTEXT_TOKENS) + list(extra_tokens)
    return any(tok in line for tok in tokens)


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return ""


def iter_text_files(
    root: Path,
    suffixes: tuple[str, ...] = (".md", ".py", ".ts", ".tsx", ".js", ".jsx",
                                  ".vue", ".yml", ".yaml", ".toml", ".json",
                                  ".txt", ".env", ".env.example", ".sh"),
    skip_dirs: tuple[str, ...] = (".git", "node_modules", ".next", "__pycache__",
                                   "dist", "build", ".venv", "venv", ".turbo",
                                   ".pytest_cache", ".mypy_cache", "coverage",
                                   "out", "target", ".cache"),
) -> Iterator[Path]:
    """递归遍历可读文本文件, 跳过 build/cache 目录."""
    if not root.is_dir():
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.suffix.lower() in suffixes or p.name in (".env", ".env.example", ".env.全栈.example"):
            yield p


def find_line_number(text: str, needle: str, start: int = 0) -> int:
    """text 中 needle 第一次出现所在行 (1-based). 找不到返回 0."""
    idx = text.find(needle, start)
    if idx < 0:
        return 0
    return text[:idx].count("\n") + 1


# 简易 entropy 用于 secret_scanner
def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    from collections import Counter
    from math import log2
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * log2(c / n) for c in counts.values())


__all__ = [
    "Finding", "ValidationResult", "Validator",
    "Severity", "EXEMPT_CONTEXT_TOKENS",
    "line_is_exempt", "safe_read", "iter_text_files",
    "find_line_number", "shannon_entropy",
]
