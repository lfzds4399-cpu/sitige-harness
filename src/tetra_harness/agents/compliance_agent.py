"""compliance_agent — 内容合规复审.

action:
  - text_review : LLM 二次扫文本 (本地 validator 之外做语义判断)
  - image_audit : stub (待对接国产 AIGC 安全 API: 万象/数美/网易易盾)
  - final_score : 综合 validator + LLM 复审打分

LLM 默认 deepseek; 文本 review 输出结构化判定 (allow/warn/block + 命中点).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from tetra_harness.agents.base import Agent, AgentResult
from tetra_harness.utils.llm_client import LLMClient

_log = logging.getLogger("tetra.agent.compliance")


_REVIEW_SYSTEM = """
你是「四面体电竞」内容合规审核员. 标红线:
1) 代练 / 外挂 / 脚本 / 改机
2) 充值返利 / 押金骗局 / 跑路诈骗
3) 未成年人参与对局 / 福利诱导
4) 涉黄 / 涉政 / 涉赌 / 涉恐
5) 平台禁词 (微信/抖音/快手/小红书各家不同)
6) 知识产权 (盗图盗音盗剧情)

输出 JSON: {
  "verdict": "allow|warn|block",
  "score": 0-100,            // 越低越危险
  "hits": [{"rule": "...", "snippet": "...", "severity": "low|mid|high"}],
  "suggest": "改写建议或 '通过'"
}
不要 Markdown, 仅 JSON.
""".strip()


def _extract_json(raw: str) -> Any:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None


class ComplianceAgent(Agent):
    name = "compliance"
    description = "内容合规 LLM 复审 + 综合评分"

    async def run(self, payload: dict, config: dict) -> AgentResult:
        action = (payload or {}).get("action", "text_review")
        with self._timed() as box:
            try:
                if action == "text_review":
                    output, cost = await self._text_review(payload, config)
                elif action == "image_audit":
                    output, cost = self._image_audit(payload, config)
                elif action == "final_score":
                    output, cost = self._final_score(payload, config)
                else:
                    return self._fail(
                        f"unknown action: {action!r}", elapsed_ms=box["elapsed_ms"]
                    )
            except Exception as e:  # noqa: BLE001
                _log.exception("compliance_agent failed")
                return self._fail(
                    f"{type(e).__name__}: {e}", elapsed_ms=box["elapsed_ms"]
                )
        return self._ok(
            output=output, cost_usd=cost, elapsed_ms=box["elapsed_ms"], action=action
        )

    async def _text_review(
        self, payload: dict, config: dict
    ) -> tuple[Any, float]:
        text = payload.get("text") or ""
        if not text:
            return {"verdict": "allow", "score": 100, "hits": [], "suggest": "空文本"}, 0.0

        platform = payload.get("platform") or config.get("platform", "douyin")
        strictness = config.get("strictness", "high")
        instr = (
            f"平台: {platform}; 严格度: {strictness}.\n"
            f"待审文本:\n---\n{text[:3000]}\n---"
        )
        msgs = [
            {"role": "system", "content": _REVIEW_SYSTEM},
            {"role": "user", "content": instr},
        ]
        client = LLMClient(provider=config.get("provider", "deepseek"))
        raw = await client.chat(msgs, model=config.get("model"), temperature=0.0)
        parsed = _extract_json(raw)
        if not parsed:
            return {
                "verdict": "warn",
                "score": 50,
                "hits": [],
                "suggest": "LLM 解析失败, 走人工",
                "_raw": raw[:500],
            }, 0.0
        return parsed, 0.0

    def _image_audit(self, payload: dict, config: dict) -> tuple[Any, float]:
        # stub — 真接需对接万象/数美/网易易盾 (¥0.001-0.01/张)
        return {
            "verdict": "stub",
            "score": None,
            "todo": "对接万象/数美/网易易盾 AIGC 安全 API",
            "image_count": len(payload.get("images") or []),
        }, 0.0

    def _final_score(self, payload: dict, config: dict) -> tuple[Any, float]:
        validator_report = payload.get("validator") or {}
        llm_review = payload.get("llm_review") or {}
        # 简单加权: validator error 直接 block; LLM score 平均
        v_errors = int(validator_report.get("error_count", 0))
        v_warns = int(validator_report.get("warn_count", 0))
        llm_score = float(llm_review.get("score", 60))
        if v_errors > 0:
            verdict = "block"
            score = 0
        elif llm_review.get("verdict") == "block":
            verdict = "block"
            score = min(llm_score, 30)
        elif v_warns > 0 or llm_review.get("verdict") == "warn":
            verdict = "warn"
            score = min(llm_score, 60)
        else:
            verdict = "allow"
            score = max(llm_score, 70)
        return {
            "verdict": verdict,
            "score": round(score, 1),
            "validator_errors": v_errors,
            "validator_warns": v_warns,
            "llm_verdict": llm_review.get("verdict"),
        }, 0.0


__all__ = ["ComplianceAgent"]
