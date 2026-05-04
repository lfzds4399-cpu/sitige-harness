"""build_health — web/server/bot/kook/miniprogram 5 模块 build/import 健康检查.

默认禁用 (慢, 可能要 5min). 显式 `tetra audit --validator build_health` 才跑.
依赖 utils.subprocess_safe.safe_run (强制 capture_output, 跨平台兜底).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .base import Validator, ValidationResult


def _safe_run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    from tetra_harness.utils.subprocess_safe import safe_run
    return safe_run(cmd, cwd=str(cwd), timeout=timeout, shell=(os.name == "nt"))


# (sub_path, cmd, timeout_sec, optional)
BUILD_TARGETS: list[tuple[str, list[str], int, bool]] = [
    ("web", ["npm", "run", "build"], 300, False),
    ("server", [sys.executable, "-c", "import sys; sys.path.insert(0,'src'); from main import app  # type: ignore"],
     30, True),
    ("bot", [sys.executable, "-c", "import sys; sys.path.insert(0,'src'); from main import app  # type: ignore"],
     30, True),
    ("kook/bot", [sys.executable, "-c", "import sys; sys.path.insert(0,'.'); import main  # type: ignore"],
     30, True),
    ("miniprogram", ["npm", "run", "build:weapp"], 300, True),
]


class BuildHealthValidator(Validator):
    name = "build_health"
    description = "web/server/bot/kook/miniprogram 5 模块 build/import 健康"

    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        cfg = (config or {}).get(self.name, {})
        if not cfg.get("enabled", False):
            with self._timed(result):
                result.add("info", "BUILD_HEALTH_SKIP",
                           "默认禁用; 显式 --validator build_health 或 enabled=true 才跑")
            return result

        with self._timed(result):
            for sub, cmd, timeout, optional in BUILD_TARGETS:
                cwd = project_root / sub
                if not cwd.is_dir():
                    if optional:
                        result.add("info", "BUILD_TARGET_MISSING",
                                   f"{sub}/ 不存在 (optional, 跳过)")
                    else:
                        result.add("warn", "BUILD_TARGET_MISSING",
                                   f"{sub}/ 不存在")
                    continue

                rc, stdout, stderr = _safe_run(cmd, cwd, timeout)
                if rc == 0:
                    result.add_ok(f"{sub}: {' '.join(cmd[:3])} OK")
                elif rc == 124:
                    result.add("error", "BUILD_TIMEOUT",
                               f"{sub}: build 超时 ({timeout}s)")
                elif rc == 127:
                    result.add("warn", "BUILD_TOOL_MISSING",
                               f"{sub}: 工具不可用: {stderr[:100]}")
                else:
                    tail = (stderr or stdout)[-500:]
                    result.add("error", "BUILD_FAILED",
                               f"{sub}: rc={rc} | {tail.strip()[:200]}")
        return result


__all__ = ["BuildHealthValidator", "BUILD_TARGETS"]
