"""compliance_pipeline — 合规审核流水线 (3 stage).

stages:
  1) text_scan   compliance_agent + compliance_validator (validator 复用 audit)
  2) image_audit compliance_agent.image_audit (stub, 待对接万象/数美/网易易盾)
  3) final_gate  综合评分 + 人工兜底队列
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tetra_harness.agents.compliance_agent import ComplianceAgent
from tetra_harness.config import HARNESS_ROOT
from tetra_harness.pipelines.base import Pipeline, Stage


def _data_dir() -> Path:
    p = HARNESS_ROOT / "data" / "compliance"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_json(name: str, data: Any) -> Path:
    p = _data_dir() / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---- runners ---- #
async def _stage_text_scan(ctx: dict, config: dict) -> dict:
    text = ctx.get("text") or config.get("mock_text") or ""
    if not text:
        return {"ok": False, "error": "no text input"}
    res = await ComplianceAgent().run(
        {"action": "text_review", "text": text,
         "platform": config.get("platform", "douyin")},
        config,
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    ctx["llm_review"] = res.output
    _save_json("text_scan.json", res.output)
    return {
        "ok": res.output.get("verdict") != "block",
        "verdict": res.output.get("verdict"),
        "score": res.output.get("score"),
        "hits_count": len(res.output.get("hits") or []),
        "count": 1,
    }


async def _stage_image_audit(ctx: dict, config: dict) -> dict:
    images = ctx.get("images") or config.get("mock_images") or []
    res = await ComplianceAgent().run(
        {"action": "image_audit", "images": images}, config
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    ctx["image_audit"] = res.output
    _save_json("image_audit.json", res.output)
    return {
        "ok": True,
        "image_count": len(images),
        "stub": True,
        "count": len(images),
    }


async def _stage_final_gate(ctx: dict, config: dict) -> dict:
    llm_review = ctx.get("llm_review") or {}
    validator_report = ctx.get("validator_report") or {}
    res = await ComplianceAgent().run(
        {
            "action": "final_score",
            "validator": validator_report,
            "llm_review": llm_review,
        },
        config,
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    out = res.output
    threshold = float(config.get("manual_review_threshold", 60))
    needs_human = out.get("verdict") == "warn" or float(out.get("score", 0)) < threshold
    out = {**out, "needs_human": needs_human, "ts": datetime.now().isoformat(timespec="seconds")}
    ctx["final"] = out
    _save_json("final_gate.json", out)
    return {
        "ok": out.get("verdict") != "block",
        "verdict": out.get("verdict"),
        "score": out.get("score"),
        "needs_human": needs_human,
        "count": 1,
    }


class CompliancePipeline(Pipeline):
    name = "compliance"
    description = "合规 3 stage: text_scan → image_audit → final_gate"

    def build_stages(self, config: dict) -> list[Stage]:
        return [
            Stage("text_scan", _stage_text_scan,
                  validators=["compliance_validator"], timeout_sec=120),
            Stage("image_audit", _stage_image_audit, timeout_sec=60),
            Stage("final_gate", _stage_final_gate, timeout_sec=15),
        ]


__all__ = ["CompliancePipeline"]
