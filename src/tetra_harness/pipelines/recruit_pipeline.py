"""recruit_pipeline — 工作室招募流水线 (5 stage).

stages:
  1) scan_channels   intel_agent → 8 渠道扫候选 (mock)
  2) outreach_draft  规则模板 → QQ群/朋友圈/电话/面谈 4 套话术
  3) qualify         screen_agent → KYC (执照/法人/经营年限)
  4) deposit         押金阶梯计算 (1.0x → 1.5x 按工作室等级)
  5) sign_offer      合同草案 + 签约 SOP 输出
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tetra_harness.agents.intel_agent import IntelAgent
from tetra_harness.config import HARNESS_ROOT
from tetra_harness.pipelines.base import Pipeline, Stage


def _data_dir() -> Path:
    p = HARNESS_ROOT / "data" / "recruit"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_json(name: str, data: Any) -> Path:
    p = _data_dir() / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---- 招募话术模板 ---- #
_OUTREACH_TEMPLATES = {
    "qq_group": (
        "【{brand}】{product} 长期招优质合作工作室. "
        "我方派单, 你方接单, 月结无押金. 详谈+我V: {contact_handle}"
    ),
    "moments": (
        "招长期合作工作室 · 分包合作 · 月结透明 · 7 天试运营. "
        "戳头像主页 v 我"
    ),
    "phone": (
        "您好, 我是 BD. 我们在做长期合作, "
        "您方便看下我们的合作政策吗? 月结透明, 不收前置押金."
    ),
    "in_person": (
        "见面要点: 1) 出执照+法人 2) 拉过往订单流水 3) 押金阶梯解释清楚 "
        "4) 7 天试运营条款 5) 反诈承诺书"
    ),
}


# ---- 押金阶梯 ---- #
def _deposit_tier(level: str, base: float) -> float:
    mult = {"S": 1.0, "A": 1.1, "B": 1.25, "C": 1.5}.get(level.upper(), 1.5)
    return round(base * mult, 2)


# ---- runners ---- #
async def _stage_scan_channels(ctx: dict, config: dict) -> dict:
    res = await IntelAgent().run(
        {"action": "scan_channels", "channels": config.get("channels")}, config
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    results = (res.output or {}).get("results", [])
    candidates: list[dict] = []
    for ch in results:
        for i in range(int(ch.get("candidates_found", 0))):
            candidates.append({
                "id": f"{ch['channel']}-CAND-{i+1:03d}",
                "channel": ch["channel"],
                "name": f"工作室{ch['channel'][:3].upper()}{i+1:02d}",
                "rank_estimate": "B",
            })
    ctx["candidates"] = candidates
    _save_json("candidates.json", {"results": results, "candidates": candidates})
    return {"ok": True, "results": candidates, "count": len(candidates), "mock": True}


async def _stage_outreach_draft(ctx: dict, config: dict) -> dict:
    cands = ctx.get("candidates") or []
    drafts = []
    for c in cands[:50]:  # 控量
        drafts.append({
            "candidate_id": c["id"],
            "channel": c["channel"],
            "qq_group": _OUTREACH_TEMPLATES["qq_group"],
            "moments": _OUTREACH_TEMPLATES["moments"],
            "phone_script": _OUTREACH_TEMPLATES["phone"],
            "in_person_brief": _OUTREACH_TEMPLATES["in_person"],
        })
    ctx["drafts"] = drafts
    _save_json("outreach_drafts.json", drafts)
    return {"ok": True, "drafts": drafts, "count": len(drafts)}


async def _stage_qualify(ctx: dict, config: dict) -> dict:
    cands = ctx.get("candidates") or []
    required = config.get("kyc_fields", ["business_license", "legal_rep", "years"])
    qualified, rejected = [], []
    for c in cands:
        # mock 输入: 假设候选人提交了 mock 资料
        mock_kyc = {
            "business_license": True,
            "legal_rep": "张三",
            "years": 2,
        }
        missing = [f for f in required if not mock_kyc.get(f)]
        # 同时跑 minor_check (法人年龄 — 这里 mock 跳过 id_card)
        if not missing:
            qualified.append({**c, "kyc": mock_kyc})
        else:
            rejected.append({**c, "missing": missing})
    ctx["qualified"] = qualified
    _save_json("qualified.json", {"qualified": qualified, "rejected": rejected})
    return {
        "ok": True, "results": qualified, "count": len(qualified),
        "rejected_count": len(rejected),
    }


async def _stage_deposit(ctx: dict, config: dict) -> dict:
    qualified = ctx.get("qualified") or []
    base = float(config.get("deposit_base_rmb", 5000))
    deposits = []
    for c in qualified:
        level = c.get("rank_estimate", "C")
        deposits.append({
            "candidate_id": c["id"],
            "level": level,
            "deposit_rmb": _deposit_tier(level, base),
            "trial_days": int(config.get("trial_days", 7)),
        })
    ctx["deposits"] = deposits
    _save_json("deposits.json", deposits)
    return {"ok": True, "items": deposits, "count": len(deposits)}


async def _stage_sign_offer(ctx: dict, config: dict) -> dict:
    deposits = ctx.get("deposits") or []
    offers = []
    for d in deposits:
        offers.append({
            "candidate_id": d["candidate_id"],
            "contract_template": "legal/合作工作室协议.md",
            "deposit_rmb": d["deposit_rmb"],
            "trial_days": d["trial_days"],
            "sop_steps": [
                "1) 双方签字盖章 (电子合同)",
                "2) 押金分两笔 (50% 立刻 / 50% 试运营满)",
                "3) 派单系统加白",
                "4) 客服群拉人",
                "5) 试运营满 7 天复核",
            ],
        })
    ctx["offers"] = offers
    p = _save_json("offers.json", offers)
    return {"ok": True, "items": offers, "count": len(offers), "path": str(p)}


class RecruitPipeline(Pipeline):
    name = "recruit"
    description = "招募 → 触达 → KYC → 押金 → 签约"

    def build_stages(self, config: dict) -> list[Stage]:
        return [
            Stage("scan_channels", _stage_scan_channels, timeout_sec=60),
            Stage("outreach_draft", _stage_outreach_draft, timeout_sec=30),
            Stage("qualify", _stage_qualify, timeout_sec=60),
            Stage("deposit", _stage_deposit, timeout_sec=15),
            Stage("sign_offer", _stage_sign_offer, timeout_sec=15),
        ]


__all__ = ["RecruitPipeline"]
