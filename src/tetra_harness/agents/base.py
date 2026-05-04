"""agents.base — Agent 抽象 + 统一返回结构.

所有 agent 必须 subclass Agent 并实现 async run(payload, config) -> AgentResult.
SKILL E1: subprocess/HTTP 必走 utils.subprocess_safe / httpx + retry.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


@dataclass
class AgentResult:
    """Agent 单次执行结果.

    - ok=True 表示业务成功; output 由各 agent 自定义结构.
    - cost_usd 累计 LLM/API 花费 (CostTracker 也会单独写盘).
    - elapsed_ms 仅用于运营观测, 非业务硬要求.
    - meta 留给上层 pipeline 透传 (例如 stage 名/重试次数).
    """

    agent: str
    ok: bool
    output: Any = None
    cost_usd: float = 0.0
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "ok": self.ok,
            "output": self.output,
            "cost_usd": round(float(self.cost_usd), 6),
            "elapsed_ms": round(float(self.elapsed_ms), 2),
            "error": self.error,
            "meta": self.meta,
        }


class Agent(ABC):
    """所有 agent 抽象基类.

    用法:
        class MyAgent(Agent):
            name = "my"
            description = "..."
            async def run(self, payload, config): ...

    pipeline 调用方式:
        result = await MyAgent().run({...}, config)
    """

    name: str = "base"
    description: str = ""

    @abstractmethod
    async def run(self, payload: dict, config: dict) -> AgentResult:
        """执行单次调用. 不抛异常 — 失败请置 ok=False + error."""
        ...

    # ---- 公用 helper ----
    @contextmanager
    def _timed(self) -> Iterator[dict[str, float]]:
        """with self._timed() as box: ... ; box['elapsed_ms'] 自动写入."""
        box: dict[str, float] = {"elapsed_ms": 0.0}
        t0 = time.perf_counter()
        try:
            yield box
        finally:
            box["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0

    def _ok(self, output: Any, *, cost_usd: float = 0.0, elapsed_ms: float = 0.0,
            **meta: Any) -> AgentResult:
        return AgentResult(
            agent=self.name, ok=True, output=output,
            cost_usd=cost_usd, elapsed_ms=elapsed_ms, meta=meta,
        )

    def _fail(self, error: str, *, output: Any = None, elapsed_ms: float = 0.0,
             **meta: Any) -> AgentResult:
        return AgentResult(
            agent=self.name, ok=False, output=output,
            error=error, elapsed_ms=elapsed_ms, meta=meta,
        )


__all__ = ["Agent", "AgentResult"]
