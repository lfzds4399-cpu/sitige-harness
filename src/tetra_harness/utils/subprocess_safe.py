"""subprocess_safe — 全项目 subprocess 统一入口.

SKILL E1: 防 Windows GBK 解码炸 / 防卡死 / 自动截 stderr 日志.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from typing import Any

_log = logging.getLogger("tetra.subprocess")


def safe_run(
    cmd: str | Sequence[str],
    *,
    timeout: int = 300,
    cwd: Any = None,
    env: Any = None,
    check: bool = False,
    shell: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """安全执行 subprocess.

    强制:
      - capture_output=True
      - text=True
      - encoding="utf-8"
      - errors="replace"  (Windows GBK 输出不会炸)
      - timeout 默认 300s

    失败 (returncode != 0) 时不抛异常 (除非 check=True), 但 log 末尾 800 字 stderr.
    """
    # 屏蔽用户重复传 capture_output / text / encoding / errors
    for k in ("capture_output", "text", "encoding", "errors"):
        kwargs.pop(k, None)

    try:
        # `shell` is controlled by the caller; this wrapper exists *because*
        # callers (Windows npm.cmd, a few CLI shellouts) explicitly need it.
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=env,
            shell=shell,  # noqa: S602 - caller-controlled, see docstring
            check=False,
            **kwargs,
        )  # nosec B602
    except subprocess.TimeoutExpired as e:
        _log.error("subprocess TIMEOUT after %ss: %s", timeout, cmd)
        # 返回一个伪 CompletedProcess 方便调用方统一处理
        return subprocess.CompletedProcess(
            args=cmd, returncode=-1, stdout="", stderr=f"[timeout {timeout}s] {e}"
        )
    except FileNotFoundError as e:
        # 命令本身不存在 (例如 Windows 上未装 pandoc/docker)
        _log.info("subprocess NOT FOUND: %s", cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="", stderr=f"[not found] {e}"
        )
    except OSError as e:
        _log.warning("subprocess OSError: %s — %s", cmd, e)
        return subprocess.CompletedProcess(
            args=cmd, returncode=-2, stdout="", stderr=f"[oserror] {e}"
        )

    if r.returncode != 0:
        tail = (r.stderr or "")[-800:]
        _log.warning(
            "subprocess rc=%s cmd=%s\n--- stderr tail ---\n%s",
            r.returncode,
            cmd,
            tail,
        )
        if check:
            raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
    return r
