"""crm_pipeline — 客服流水线 (4 stage).

stages:
  1) intake          收工单 (QQ/KOOK/小程序入口, 这里直接读 ctx['ticket'])
  2) route           crm_agent classify → 退款/技术/咨询/投诉/其它
  3) auto_reply      RAG + LLM 出建议回复
  4) human_handoff   置信度 < 阈值 / 敏感等级高 → 转人工
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tetra_harness.agents.crm_agent import CRMAgent
from tetra_harness.config import HARNESS_ROOT
from tetra_harness.pipelines.base import Pipeline, Stage


def _data_dir() -> Path:
    p = HARNESS_ROOT / "data" / "crm"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_json(name: str, data: Any) -> Path:
    p = _data_dir() / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


_SENSITIVE = {"投诉", "举报", "曝光", "315", "媒体", "公安", "起诉"}


async def _stage_intake(ctx: dict, config: dict) -> dict:
    ticket = ctx.get("ticket") or config.get("mock_ticket") or {
        "ticket_id": f"TK-{datetime.now():%Y%m%d%H%M%S}",
        "user_id": "U-CRM-001",
        "channel": "qq",
        "text": "我想问下退款怎么走?",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    ctx["ticket"] = ticket
    return {"ok": True, "ticket": ticket, "count": 1}


async def _stage_route(ctx: dict, config: dict) -> dict:
    ticket = ctx.get("ticket") or {}
    agent = CRMAgent()
    res = await agent.run({"action": "classify", "text": ticket.get("text", "")}, config)
    if not res.ok:
        return {"ok": False, "error": res.error}
    cat = res.output.get("category", "other")
    ctx["category"] = cat
    ctx["route"] = res.output
    return {"ok": True, "category": cat, "confidence": res.output.get("confidence"), "count": 1}


async def _stage_auto_reply(ctx: dict, config: dict) -> dict:
    ticket = ctx.get("ticket") or {}
    agent = CRMAgent()
    res = await agent.run(
        {"action": "auto_reply", "text": ticket.get("text", "")},
        config,
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    ctx["reply"] = res.output
    _save_json(f"reply_{ticket.get('ticket_id','x')}.json", res.output)
    return {
        "ok": True,
        "reply_preview": (res.output.get("reply") or "")[:80],
        "confidence": res.output.get("confidence"),
        "auto_send": res.output.get("auto_send"),
        "count": 1,
    }


async def _stage_human_handoff(ctx: dict, config: dict) -> dict:
    ticket = ctx.get("ticket") or {}
    reply = ctx.get("reply") or {}
    cat = ctx.get("category") or "other"
    text = ticket.get("text", "")
    sensitive = any(k in text for k in _SENSITIVE)
    handoff = (
        bool(reply.get("handoff"))
        or sensitive
        or cat == "complaint"
    )
    payload = {
        "ticket_id": ticket.get("ticket_id"),
        "category": cat,
        "sensitive": sensitive,
        "handoff": handoff,
        "reason": (
            "complaint" if cat == "complaint"
            else "sensitive_keyword" if sensitive
            else "low_confidence" if reply.get("handoff")
            else "auto_send"
        ),
    }
    ctx["handoff"] = payload
    _save_json(f"handoff_{ticket.get('ticket_id','x')}.json", payload)
    return {"ok": True, "handoff": handoff, "reason": payload["reason"], "count": 1}


class CRMPipeline(Pipeline):
    name = "crm"
    description = "客服 4 stage: intake → route → auto_reply → human_handoff"

    def build_stages(self, config: dict) -> list[Stage]:
        return [
            Stage("intake", _stage_intake, timeout_sec=10),
            Stage("route", _stage_route, timeout_sec=30),
            Stage("auto_reply", _stage_auto_reply, timeout_sec=60),
            Stage("human_handoff", _stage_human_handoff, timeout_sec=10),
        ]


__all__ = ["CRMPipeline"]
