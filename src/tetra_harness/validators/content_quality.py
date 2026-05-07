"""content_quality — content/本周内容/*.md LLM 评分 + 占位符检测.

LLM 部分默认禁用 (跑一次 ¥1-5), 通过 config['content_quality']['enabled']=True 开.
占位符检测永远跑.

LLM 评分维度: 钩子强度 / 信息密度 / 合规风险 / 转化潜力 (0-10).
评分 < 6 → warn.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import ValidationResult, Validator, safe_read

# 常见占位符 — 出现这些且没标"上线后替换"或"示例" → warn
PLACEHOLDER_PATTERNS = [
    re.compile(r"师傅\s*[A-D]"),                     # 师傅 A / 师傅 B
    re.compile(r"客户\s*[百千万]+回血"),                # 客户百万回血
    re.compile(r"客户\s*[A-D]\s*"),
    re.compile(r"\bxxx\b", re.IGNORECASE),
    re.compile(r"TODO|TBD|待补|待填", re.IGNORECASE),
    re.compile(r"\[占位\]|\[待替换\]|\[TODO\]"),
    re.compile(r"￥[xX*]+|¥[xX*]+"),                # ￥xxx / ¥***
]

PLACEHOLDER_EXEMPT_TOKENS = (
    "示例", "例如", "样例", "占位说明", "上线后替换", "上线前替换",
    "下面是占位", "占位文本", "占位符说明", "格式参考",
)


def _scan_placeholders(text: str) -> list[tuple[int, str]]:
    """返回 [(line_no, matched_str)]; 跳过明确"占位说明"上下文."""
    hits = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if any(t in line for t in PLACEHOLDER_EXEMPT_TOKENS):
            continue
        for pat in PLACEHOLDER_PATTERNS:
            m = pat.search(line)
            if m:
                hits.append((line_no, m.group(0)))
                break
    return hits


def _try_llm_score(text: str) -> dict | None:
    """调 DeepSeek 评 4 维分; 失败返回 None.

    依赖 utils.llm_client 由基建 agent 提供; 没有就跳过.
    """
    try:
        from tetra_harness.utils.llm_client import LLMClient  # type: ignore
    except Exception:
        return None

    prompt = f"""你是抖音/小红书运营审稿人. 给下列文案打 4 项 0-10 分:
1. 钩子强度 (前 3 秒抓人能力)
2. 信息密度 (干货/技巧/数据)
3. 合规风险 (越高越危险, 涉广告法/平台禁词/未保红线)
4. 转化潜力 (引私域/下单/收藏)

只返回 JSON, 形如 {{"hook":7, "density":6, "risk":3, "conversion":8, "summary":"一句话"}}.

文案:
{text[:3000]}
"""
    try:
        client = LLMClient()  # type: ignore
        resp = client.complete(prompt, model="deepseek-chat", max_tokens=200, temperature=0.2)
        # 提 JSON
        m = re.search(r"\{[^{}]+\}", resp)
        if not m:
            return None
        return json.loads(m.group(0))
    except Exception:
        return None


class ContentQualityValidator(Validator):
    name = "content_quality"
    description = "content/本周内容/*.md 占位符检测 + (可选) LLM 4 维评分"

    def run(self, project_root: Path, config: dict | None = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        cfg = (config or {}).get(self.name, {})
        llm_enabled = bool(cfg.get("enabled", False))

        with self._timed(result):
            content_dir = project_root / "content/本周内容"
            if not content_dir.is_dir():
                result.add("warn", "CONTENT_DIR_MISSING",
                           "content/本周内容/ 目录不存在")
                return result

            md_files = list(content_dir.glob("*.md"))
            if not md_files:
                result.add("warn", "CONTENT_EMPTY", "本周内容/ 无 .md")
                return result

            for f in md_files:
                text = safe_read(f)
                if not text:
                    continue

                # 占位符检测
                placeholders = _scan_placeholders(text)
                if placeholders:
                    line_no, matched = placeholders[0]
                    result.add(
                        "warn", "CONTENT_PLACEHOLDER",
                        f"[{f.name}] 含 {len(placeholders)} 处未替换占位符 (首处: '{matched}')",
                        file=f, line=line_no,
                    )
                else:
                    result.add_ok(f"[{f.name}] 无未替换占位符")

                # LLM 评分 (可选)
                if llm_enabled:
                    score = _try_llm_score(text)
                    if score is None:
                        result.add("info", "LLM_UNAVAILABLE",
                                   f"[{f.name}] LLM 不可用, 跳过评分", file=f)
                        continue
                    fail = []
                    for dim in ("hook", "density", "conversion"):
                        v = score.get(dim, 0)
                        if isinstance(v, (int, float)) and v < 6:
                            fail.append(f"{dim}={v}")
                    risk = score.get("risk", 0)
                    if isinstance(risk, (int, float)) and risk >= 7:
                        fail.append(f"risk={risk}")
                    if fail:
                        result.add(
                            "warn", "CONTENT_LOW_SCORE",
                            f"[{f.name}] 弱项: {', '.join(fail)} | {score.get('summary','')}",
                            file=f,
                        )
                    else:
                        result.add_ok(f"[{f.name}] LLM 评分通过")
        return result


__all__ = ["ContentQualityValidator", "PLACEHOLDER_PATTERNS"]
