"""match_agent — 派单 6 因子算法代理.

调用 server 端 `POST <SERVER_URL>/api/match` 跑算法, 返回最佳师傅 + 评分明细.
server down 时降级: 返回 ok=False + 入降级队列 (上层 pipeline 处理).

6 因子 (server 端实现, 这里只透传 weights):
  1) 段位匹配  2) 评分历史  3) 物理位置  4) 语言偏好  5) 时段可用  6) 历史合作
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from tetra_harness.agents.base import Agent, AgentResult
from tetra_harness.config import get_env
from tetra_harness.utils.retry import retry_with_backoff

_log = logging.getLogger("tetra.agent.match")


@retry_with_backoff(max=2, exp=2, min_wait=0.5, max_wait=5.0)
async def _call_match_api(
    base_url: str, payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/match"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


class MatchAgent(Agent):
    name = "match"
    description = "派单 6 因子算法 (调 server API)"

    async def run(self, payload: dict, config: dict) -> AgentResult:
        order = (payload or {}).get("order") or {}
        if not order.get("order_id"):
            return self._fail("missing order.order_id")

        base_url: Optional[str] = (
            payload.get("server_url")
            or config.get("server_url")
            or get_env("TETRA_SERVER_URL")
        )
        timeout = float(config.get("timeout_sec", 8))
        weights = config.get(
            "weights",
            {
                "rank": 0.25,
                "rating": 0.25,
                "geo": 0.10,
                "language": 0.10,
                "schedule": 0.15,
                "history": 0.15,
            },
        )

        body = {
            "order_id": order["order_id"],
            "user_segment": payload.get("user_segment", order.get("user_segment")),
            "urgency": payload.get("urgency", order.get("urgency", "normal")),
            "weights": weights,
        }

        with self._timed() as box:
            # 没配 server URL → 降级 mock (本地测试 / 离线)
            if not base_url:
                _log.warning("TETRA_SERVER_URL 未配置, match 走本地 mock")
                output = {
                    "order_id": body["order_id"],
                    "master_id": "MOCK-M-0001",
                    "score": 0.78,
                    "factors": {k: round(v * 0.8, 3) for k, v in weights.items()},
                    "fallback": True,
                    "reason": "server_url_missing",
                }
                return self._ok(output=output, elapsed_ms=box["elapsed_ms"], mock=True)

            try:
                output = await _call_match_api(base_url, body, timeout)
            except httpx.HTTPError as e:
                _log.warning("match server unreachable: %s", e)
                return self._fail(
                    f"server_unreachable: {type(e).__name__}",
                    output={"order_id": body["order_id"], "queued_for_fallback": True},
                    elapsed_ms=box["elapsed_ms"],
                )
            except Exception as e:  # noqa: BLE001
                _log.exception("match unexpected error")
                return self._fail(
                    f"{type(e).__name__}: {e}", elapsed_ms=box["elapsed_ms"]
                )

        return self._ok(output=output, elapsed_ms=box["elapsed_ms"])


__all__ = ["MatchAgent"]
