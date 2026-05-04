"""retry — tenacity 包装的指数退避重试装饰器."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

_log = logging.getLogger("tetra.retry")

# 默认重试的异常类型: 网络/超时
_DEFAULT_EXC: tuple[type[BaseException], ...] = (
    httpx.HTTPError,
    httpx.TimeoutException,
    asyncio.TimeoutError,
    ConnectionError,
)


def retry_with_backoff(
    max: int = 3,
    exp: float = 2.0,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = _DEFAULT_EXC,
) -> Callable[..., Any]:
    """指数退避重试装饰器.

    用法:
        @retry_with_backoff(max=3, exp=2)
        async def call_api(...): ...
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(max),
        wait=wait_exponential(multiplier=min_wait, exp_base=exp, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        before_sleep=before_sleep_log(_log, logging.WARNING),
    )
