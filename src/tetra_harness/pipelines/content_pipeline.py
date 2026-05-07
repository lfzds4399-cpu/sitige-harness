"""content_pipeline — 内容生产流水线 (5 stage).

stages:
  1) select_topic       content_agent → 5 选题候选
  2) generate_script    content_agent → 全脚本 (分镜/台词/字幕)
  3) aigc_assets        content_agent → AIGC prompt + 检查清单 (operator 手动到即梦/可灵)
  4) compliance_review  compliance_agent → LLM 复审 (allow/warn/block)
  5) publish_brief      聚合产物 → brief.md (周日历/配图清单)
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tetra_harness.agents.compliance_agent import ComplianceAgent
from tetra_harness.agents.content_agent import ContentAgent
from tetra_harness.config import HARNESS_ROOT
from tetra_harness.pipelines.base import Pipeline, Stage


def _data_dir() -> Path:
    p = HARNESS_ROOT / "data" / "content"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_json(name: str, data: Any) -> Path:
    p = _data_dir() / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---- runners ---- #
async def _stage_select_topic(ctx: dict, config: dict) -> dict:
    candidates = int(config.get("candidates", 5))
    res = await ContentAgent().run(
        {"action": "select_topic", "candidates": candidates}, config
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    topics = (res.output or {}).get("topics", [])
    ctx["topics"] = topics
    _save_json("topics.json", res.output)
    return {"ok": True, "topics": topics, "count": len(topics)}


async def _stage_generate_script(ctx: dict, config: dict) -> dict:
    topics = ctx.get("topics") or []
    if not topics:
        return {"ok": False, "error": "no topics from previous stage"}
    pick = topics[0]  # 默认头条; 真实场景由人工/规则筛
    res = await ContentAgent().run(
        {"action": "generate_script", "topic": pick}, config
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    ctx["script"] = res.output
    _save_json("script.json", res.output)
    shots = (res.output or {}).get("shots") or []
    return {"ok": True, "script": res.output, "shots": shots}


async def _stage_aigc_assets(ctx: dict, config: dict) -> dict:
    script = ctx.get("script") or {}
    res = await ContentAgent().run(
        {"action": "aigc_prompt", "script": script}, config
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    ctx["aigc"] = res.output
    _save_json("aigc_prompts.json", res.output)
    prompts = (res.output or {}).get("prompts") or []
    return {"ok": True, "prompts": prompts, "count": len(prompts)}


async def _stage_compliance_review(ctx: dict, config: dict) -> dict:
    script = ctx.get("script") or {}
    text = json.dumps(script, ensure_ascii=False)
    res = await ComplianceAgent().run(
        {"action": "text_review", "text": text,
         "platform": (config.get("platforms") or ["douyin"])[0]},
        config,
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    ctx["compliance"] = res.output
    _save_json("compliance.json", res.output)
    verdict = (res.output or {}).get("verdict")
    return {"ok": verdict != "block", "verdict": verdict, "review": res.output}


async def _stage_publish_brief(ctx: dict, config: dict) -> dict:
    topics = ctx.get("topics") or []
    script = ctx.get("script") or {}
    aigc = ctx.get("aigc") or {}
    compliance = ctx.get("compliance") or {}

    today = date.today()
    cal_lines = []
    for i, t in enumerate(topics[:7]):
        d = today + timedelta(days=i)
        cal_lines.append(
            f"- {d.isoformat()} · {t.get('platform','?')} · {t.get('title','-')} (hook: {t.get('hook','-')})"
        )

    brief_md = f"""# 四面体电竞 · 本周内容发布 brief

## 1. 周日历 (基于 {len(topics)} 选题)
{chr(10).join(cal_lines) or '- (无候选)'}

## 2. 头条脚本
- title: {script.get('shots', [{}])[0].get('voiceover','-') if script.get('shots') else (topics[0].get('title','-') if topics else '-')}
- hook: {script.get('hook','-')}
- shots: {len(script.get('shots') or [])} 段
- CTA: {script.get('cta','-')}

## 3. AIGC 配图清单
- prompts: {len(aigc.get('prompts') or [])} 条
- checklist: {len(aigc.get('checklist') or [])} 条

## 4. 合规结论
- verdict: **{compliance.get('verdict','-')}**
- score: {compliance.get('score','-')}
- hits: {len(compliance.get('hits') or [])}
- suggest: {compliance.get('suggest','-')}

> 自动生成 — pipeline=content
"""
    p = _data_dir() / "brief.md"
    p.write_text(brief_md, encoding="utf-8")
    return {"ok": True, "brief_path": str(p), "count": len(topics)}


class ContentPipeline(Pipeline):
    name = "content"
    description = "选题→脚本→AIGC→合规→发布 brief"

    def build_stages(self, config: dict) -> list[Stage]:
        return [
            Stage("select_topic", _stage_select_topic, validators=[], timeout_sec=120),
            Stage("generate_script", _stage_generate_script, validators=[], timeout_sec=180),
            Stage("aigc_assets", _stage_aigc_assets, validators=[], timeout_sec=120),
            Stage("compliance_review", _stage_compliance_review,
                  validators=["compliance_validator"], timeout_sec=120),
            Stage("publish_brief", _stage_publish_brief, validators=[], timeout_sec=30),
        ]


__all__ = ["ContentPipeline"]
