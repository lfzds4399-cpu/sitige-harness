"""content_agent — 内容创作智能体.

action:
  - select_topic   : 出 N 个选题候选 (含平台/钩子/转化估算)
  - generate_script: 选定 1 个选题, 出全脚本 (开场/分镜/台词/字幕/CTA)
  - aigc_prompt    : 出图/视频生成的 AIGC prompt + 检查清单 (operator 手动到即梦/可灵)

LLM 默认 deepseek (国产优先), 模型/provider 可在 config 覆盖.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from tetra_harness.agents.base import Agent, AgentResult
from tetra_harness.utils.llm_client import LLMClient

_log = logging.getLogger("tetra.agent.content")


# ---------------- prompt 模板 ---------------- #
_BRAND_BRIEF = """
你是「四面体电竞」内容主笔. 品牌人设:
- 业务: 三角洲行动 撤离 / 陪练 / 工作室分包 / 留学生友好.
- 调性: 兄弟向 · 实战派 · 黑金硬朗 · 不油腻不土味.
- 红线: 不得提及代练 / 外挂 / 充值 / 灰色话术 / 押金返利等违规词.
- 钩子方向: 高分段实战, 大佬本人解说, 队友 carry 名场面, 反诈防骗.

输出全部 JSON, 不要任何 Markdown 装饰.
""".strip()


def _system_msg(extra: str = "") -> dict[str, Any]:
    content = _BRAND_BRIEF + ("\n\n" + extra if extra else "")
    return {"role": "system", "content": content}


def _extract_json(raw: str) -> Any:
    """从 LLM 输出中拎 JSON. LLM 偶尔会带 ```json fences."""
    s = raw.strip()
    # 去 fences
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 尝试抓第一对 {...} 或 [...]
        m = re.search(r"(\{.*\}|\[.*\])", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None


# ---------------- agent 实现 ---------------- #
class ContentAgent(Agent):
    name = "content"
    description = "选题/脚本/AIGC prompt 三连"

    async def run(self, payload: dict, config: dict) -> AgentResult:
        action = (payload or {}).get("action", "select_topic")
        with self._timed() as box:
            try:
                if action == "select_topic":
                    output, cost = await self._select_topic(payload, config)
                elif action == "generate_script":
                    output, cost = await self._generate_script(payload, config)
                elif action == "aigc_prompt":
                    output, cost = await self._aigc_prompt(payload, config)
                else:
                    return self._fail(
                        f"unknown action: {action!r}", elapsed_ms=box["elapsed_ms"]
                    )
            except Exception as e:  # noqa: BLE001
                _log.exception("content_agent failed")
                return self._fail(
                    f"{type(e).__name__}: {e}", elapsed_ms=box["elapsed_ms"]
                )
        return self._ok(
            output=output, cost_usd=cost, elapsed_ms=box["elapsed_ms"], action=action
        )

    # ---- 子动作 ---- #
    async def _select_topic(
        self, payload: dict, config: dict
    ) -> tuple[Any, float]:
        platforms = config.get("platforms", ["douyin", "xiaohongshu", "bilibili"])
        weekly = config.get("weekly_count", {})
        keywords = config.get("brand_keywords", [])
        tone = config.get("tone", "兄弟向 / 实战派")
        candidates = int(payload.get("candidates", 5))

        instr = (
            f"出 {candidates} 个本周选题候选. 平台覆盖: {platforms}. "
            f"周配额参考: {weekly}. 品牌关键词: {keywords}. 调性: {tone}.\n"
            "每条返回字段: title, platform, hook(钩子句), angle(切入角度), "
            "format(图文/短视频/长视频), est_engagement(预估互动 1-10), "
            "est_conversion(预估转化 1-10).\n"
            "返回顶层 JSON: {\"topics\": [...]}"
        )
        msgs = [_system_msg(), {"role": "user", "content": instr}]
        client = LLMClient(provider=config.get("provider", "deepseek"))
        raw = await client.chat(msgs, model=config.get("model"), temperature=0.7)
        parsed = _extract_json(raw) or {"topics": [], "_raw": raw[:500]}
        # 估算单次成本 (cost_tracker 已记账, 这里只回报)
        return parsed, 0.0

    async def _generate_script(
        self, payload: dict, config: dict
    ) -> tuple[Any, float]:
        topic = payload.get("topic") or {}
        if not topic:
            return {"error": "missing topic"}, 0.0

        instr = (
            "为以下选题写完整短视频脚本(60-90s). 字段:\n"
            "  hook (3 秒钩子台词), shots (分镜列表 5-8 段, 每段含 visual/voiceover/duration_sec), "
            "  caption (字幕全文), cta (引流话术), platform_tags (平台标签), risk_note (合规提醒).\n"
            f"选题输入: {json.dumps(topic, ensure_ascii=False)}\n"
            "返回 JSON, 不要 Markdown."
        )
        msgs = [_system_msg(), {"role": "user", "content": instr}]
        client = LLMClient(provider=config.get("provider", "deepseek"))
        raw = await client.chat(msgs, model=config.get("model"), temperature=0.6)
        parsed = _extract_json(raw) or {"error": "parse_failed", "_raw": raw[:500]}
        return parsed, 0.0

    async def _aigc_prompt(
        self, payload: dict, config: dict
    ) -> tuple[Any, float]:
        script = payload.get("script") or {}
        instr = (
            "把以下脚本的每个分镜转成 AIGC 生成 prompt (即梦/可灵适配, 中英双语). "
            "另出一份'人工检查清单' (色调/品牌色 #FFD700 黑金 / 禁忌镜头).\n"
            f"脚本: {json.dumps(script, ensure_ascii=False)[:3000]}\n"
            "返回 JSON: {prompts: [...], checklist: [...]}"
        )
        msgs = [_system_msg("注意: 不输出真实武器、未成年角色、赌博暗示."),
                {"role": "user", "content": instr}]
        client = LLMClient(provider=config.get("provider", "deepseek"))
        raw = await client.chat(msgs, model=config.get("model"), temperature=0.4)
        parsed = _extract_json(raw) or {"prompts": [], "checklist": [], "_raw": raw[:500]}
        return parsed, 0.0


__all__ = ["ContentAgent"]
