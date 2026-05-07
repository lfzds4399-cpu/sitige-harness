"""logging_setup — 双 handler (console quiet + file 永远全量).

SKILL E1 必备模式: Claude Code 等环境用 quiet=True 省上下文,
file handler 永远写 INFO 级别全量, 出错可回查.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    from rich.logging import RichHandler

    _HAS_RICH = True
except ImportError:  # pragma: no cover
    _HAS_RICH = False


_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(
    name: str = "tetra",
    quiet: bool = False,
    log_dir: Path | None = None,
    level: str = "INFO",
) -> logging.Logger:
    """配置 logger.

    quiet=True   console 仅 WARNING+ (节省 Claude Code 上下文)
    quiet=False  console INFO+
    file handler 永远 INFO 级写盘, 文件名 pipeline_YYYYMMDD_HHMMSS.log
    """
    handlers: list[logging.Handler] = []
    file_level = logging.INFO  # 文件永远 INFO
    console_level = logging.WARNING if quiet else getattr(logging, level.upper(), logging.INFO)

    # ---- console ----
    if _HAS_RICH:
        rh = RichHandler(rich_tracebacks=True, show_time=True, show_path=False, markup=False)
        rh.setLevel(console_level)
        handlers.append(rh)
    else:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter(_FORMAT))
        ch.setLevel(console_level)
        handlers.append(ch)

    # ---- file (可选) ----
    log_path: Path | None = None
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FORMAT))
        fh.setLevel(file_level)
        handlers.append(fh)

    # root level 必须 ≤ 较细的那个 handler
    root_level = min(console_level, file_level) if log_dir else console_level
    logging.basicConfig(level=root_level, handlers=handlers, force=True)

    # 噪声库压低
    for noisy in ("urllib3", "requests", "httpx", "httpcore", "openai", "PIL", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger = logging.getLogger(name)
    if log_path is not None:
        # 暴露日志文件路径方便 CLI 提示
        logger.log_path = log_path  # type: ignore[attr-defined]
    return logger
