"""match_pipeline — 派单流水线 (6 stage).

stages:
  1) intake     接单 (server /api/orders 模拟)
  2) screen     screen_agent KYC + 黑名单 + 未保
  3) match      match_agent 6 因子 (调 server /api/match)
  4) dispatch   推 KOOK + QQ + 微信 三栈通知 (mock)
  5) track      进度跟踪 + 超时降级
  6) settle     结算 + 评价回收 (mock)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tetra_harness.agents.match_agent import MatchAgent
from tetra_harness.agents.screen_agent import ScreenAgent
from tetra_harness.config import HARNESS_ROOT
from tetra_harness.pipelines.base import Pipeline, Stage

_log = logging.getLogger("tetra.pipeline.match")


def _data_dir() -> Path:
    p = HARNESS_ROOT / "data" / "match"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_json(name: str, data: Any) -> Path:
    p = _data_dir() / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---- runners ---- #
async def _stage_intake(ctx: dict, config: dict) -> dict:
    # 真实场景由 server 推; pipeline 单独跑用 ctx['order'] 或 config['mock_order']
    order = ctx.get("order") or config.get("mock_order") or {
        "order_id": f"ORD-{datetime.now():%Y%m%d%H%M%S}",
        "user_id": "U-MOCK-001",
        "user_segment": "regular",
        "urgency": "normal",
        "id_card": "",
        "service": "撤离陪练 · 大佬带飞",
    }
    ctx["order"] = order
    _save_json(f"intake_{order['order_id']}.json", order)
    return {"ok": True, "order": order, "count": 1}


async def _stage_screen(ctx: dict, config: dict) -> dict:
    order = ctx.get("order") or {}
    agent = ScreenAgent()
    bl_cfg = {**config, "blacklist_path": config.get("blacklist_path")}
    bl_res = await agent.run({"action": "blacklist", "token": order.get("user_id")}, bl_cfg)
    minor_res = await agent.run({"action": "minor_check", "id_card": order.get("id_card", "")}, config)
    blocked = (not bl_res.output.get("passed", True)) or (
        order.get("id_card") and not minor_res.output.get("passed", True)
    )
    ctx["screen"] = {"blacklist": bl_res.output, "minor": minor_res.output, "blocked": blocked}
    return {
        "ok": not blocked,
        "blocked": blocked,
        "blacklist_hit": bl_res.output.get("hit"),
        "is_minor": minor_res.output.get("is_minor"),
        "count": 1,
    }


async def _stage_match(ctx: dict, config: dict) -> dict:
    order = ctx.get("order") or {}
    res = await MatchAgent().run(
        {
            "order": order,
            "user_segment": order.get("user_segment"),
            "urgency": order.get("urgency"),
            "server_url": config.get("server_url"),
        },
        config,
    )
    ctx["match"] = res.output
    _save_json(f"match_{order.get('order_id','x')}.json", res.output)
    if not res.ok:
        # 入降级队列
        return {"ok": True, "fallback": True, "queued": res.output, "count": 1}
    return {"ok": True, "master_id": res.output.get("master_id"),
            "score": res.output.get("score"), "count": 1}


async def _stage_dispatch(ctx: dict, config: dict) -> dict:
    order = ctx.get("order") or {}
    match = ctx.get("match") or {}
    if not match or match.get("queued_for_fallback"):
        return {"ok": True, "skipped": True, "reason": "no match", "count": 0}
    notifications = []
    for ch in config.get("dispatch_channels", ["kook", "qq", "wechat"]):
        notifications.append({
            "channel": ch,
            "order_id": order.get("order_id"),
            "master_id": match.get("master_id"),
            "ts": datetime.now().isoformat(timespec="seconds"),
            "sent": True,
            "mock": True,
        })
    ctx["dispatch"] = notifications
    _save_json(f"dispatch_{order.get('order_id','x')}.json", notifications)
    return {"ok": True, "notifications": notifications, "count": len(notifications)}


async def _stage_track(ctx: dict, config: dict) -> dict:
    order = ctx.get("order") or {}
    timeout_min = int(config.get("ack_timeout_min", 5))
    # mock: 假设 80% 接单, 20% 走降级链
    accepted = True  # mock
    ctx["track"] = {
        "order_id": order.get("order_id"),
        "accepted": accepted,
        "ack_deadline": (datetime.now() + timedelta(minutes=timeout_min)).isoformat(),
        "fallback_chain": config.get("fallback_chain", ["secondary_master", "open_bid"]),
    }
    return {"ok": accepted, "accepted": accepted, "count": 1}


async def _stage_settle(ctx: dict, config: dict) -> dict:
    order = ctx.get("order") or {}
    match = ctx.get("match") or {}
    settlement = {
        "order_id": order.get("order_id"),
        "master_id": match.get("master_id"),
        "amount_rmb": float(config.get("default_amount_rmb", 99)),
        "rating": 5,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "mock": True,
    }
    ctx["settle"] = settlement
    _save_json(f"settle_{order.get('order_id','x')}.json", settlement)
    return {"ok": True, "settlement": settlement, "count": 1}


class MatchPipeline(Pipeline):
    name = "match"
    description = "派单 6 stage: intake → screen → match → dispatch → track → settle"

    def build_stages(self, config: dict) -> list[Stage]:
        return [
            Stage("intake", _stage_intake, timeout_sec=10),
            Stage("screen", _stage_screen, timeout_sec=15),
            Stage("match", _stage_match, validators=[], timeout_sec=15, skip_on_error=True),
            Stage("dispatch", _stage_dispatch, timeout_sec=15, skip_on_error=True),
            Stage("track", _stage_track, timeout_sec=10),
            Stage("settle", _stage_settle, timeout_sec=10),
        ]


__all__ = ["MatchPipeline"]
