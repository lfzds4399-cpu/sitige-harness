"""crm_agent — 客服 RAG 自动回复.

action:
  - classify    : 工单分流 (退款/技术/咨询/投诉/其它)
  - retrieve    : 知识库检索 (BM25-lite 起步, 不强求 embedding)
  - auto_reply  : 检索 + LLM 生成建议回复 (置信度 + 是否转人工)

知识库目录由 config.knowledge_base_paths 指定, 默认:
  legal/, ops/客服话术库.md, risk/平台关键词审核表.md
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tetra_harness.agents.base import Agent, AgentResult
from tetra_harness.utils.llm_client import LLMClient

_log = logging.getLogger("tetra.agent.crm")


# ------------ 知识库加载 + BM25-lite ------------ #
_TOKEN_RE = re.compile(r"[一-龥]|[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    """简易中英混合切词: 中文按字, 英文按词."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _walk_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    yield from root.rglob("*.md")


def _chunk_text(path: Path, max_chars: int = 600) -> list[tuple[str, str]]:
    """按 markdown 段落切, 返回 [(chunk_id, text), ...]."""
    raw = ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    parts = re.split(r"\n\s*\n", raw)
    out: list[tuple[str, str]] = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        # 长段落再硬切
        for j in range(0, len(p), max_chars):
            chunk = p[j : j + max_chars]
            cid = f"{path.name}#chunk{i}-{j}"
            out.append((cid, chunk))
    return out


class _KB:
    """轻量 BM25 实现, 进程内 cache."""

    def __init__(self) -> None:
        self.docs: list[tuple[str, str, list[str]]] = []  # (id, raw, tokens)
        self.df: Counter[str] = Counter()
        self.avg_dl: float = 0.0
        self._loaded_paths: tuple[str, ...] = ()

    def load(self, paths: list[str], project_root: Path) -> None:
        key = tuple(sorted(paths))
        if key == self._loaded_paths and self.docs:
            return  # cache hit
        self.docs.clear()
        self.df.clear()
        for raw in paths:
            p = (project_root / raw) if not Path(raw).is_absolute() else Path(raw)
            for fp in _walk_files(p):
                for cid, text in _chunk_text(fp):
                    toks = _tokenize(text)
                    if not toks:
                        continue
                    self.docs.append((cid, text, toks))
                    for t in set(toks):
                        self.df[t] += 1
        self.avg_dl = (
            sum(len(t) for _, _, t in self.docs) / len(self.docs)
            if self.docs
            else 0.0
        )
        self._loaded_paths = key

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self.docs:
            return []
        q_toks = _tokenize(query)
        if not q_toks:
            return []
        n = len(self.docs)
        k1, b = 1.5, 0.75
        scored: list[tuple[float, str, str]] = []
        for cid, text, toks in self.docs:
            tf = Counter(toks)
            dl = len(toks)
            score = 0.0
            for q in q_toks:
                if q not in tf:
                    continue
                df = self.df.get(q, 0)
                if df == 0:
                    continue
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
                num = tf[q] * (k1 + 1)
                den = tf[q] + k1 * (1 - b + b * dl / max(self.avg_dl, 1.0))
                score += idf * num / den
            if score > 0:
                scored.append((score, cid, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": cid, "score": round(s, 3), "snippet": text[:300]}
            for s, cid, text in scored[:top_k]
        ]


_KB_SINGLETON = _KB()


# ------------ Agent ------------ #
class CRMAgent(Agent):
    name = "crm"
    description = "工单分流 + RAG 自动回复"

    async def run(self, payload: dict, config: dict) -> AgentResult:
        action = (payload or {}).get("action", "auto_reply")
        with self._timed() as box:
            try:
                if action == "classify":
                    output, cost = await self._classify(payload, config)
                elif action == "retrieve":
                    output, cost = self._retrieve(payload, config)
                elif action == "auto_reply":
                    output, cost = await self._auto_reply(payload, config)
                else:
                    return self._fail(
                        f"unknown action: {action!r}", elapsed_ms=box["elapsed_ms"]
                    )
            except Exception as e:  # noqa: BLE001
                _log.exception("crm_agent failed")
                return self._fail(
                    f"{type(e).__name__}: {e}", elapsed_ms=box["elapsed_ms"]
                )
        return self._ok(
            output=output, cost_usd=cost, elapsed_ms=box["elapsed_ms"], action=action
        )

    # ---- helpers ---- #
    def _project_root(self, config: dict) -> Path:
        # config 可显式给, 否则取包根的祖父 (harness/.. = 项目根)
        from tetra_harness.config import HARNESS_ROOT
        root = config.get("project_root") or HARNESS_ROOT.parent
        return Path(root)

    def _ensure_kb(self, config: dict) -> None:
        paths = config.get("knowledge_base_paths") or [
            "legal", "ops/客服话术库.md", "risk/平台关键词审核表.md",
        ]
        _KB_SINGLETON.load(paths, self._project_root(config))

    # ---- actions ---- #
    async def _classify(
        self, payload: dict, config: dict
    ) -> tuple[Any, float]:
        text = (payload.get("text") or "").strip()
        if not text:
            return {"category": "other", "confidence": 0.0}, 0.0
        # 关键词快速分类 (LLM 兜底)
        kw_map = {
            "refund": ["退款", "退钱", "不玩了", "申诉"],
            "technical": ["登不上", "卡顿", "黑屏", "闪退", "bug"],
            "consult": ["怎么", "多少钱", "能不能", "咨询"],
            "complaint": ["投诉", "举报", "差评", "态度"],
        }
        for cat, kws in kw_map.items():
            if any(k in text for k in kws):
                return {"category": cat, "confidence": 0.85, "by": "rule"}, 0.0

        # LLM 兜底
        msgs = [
            {"role": "system", "content": "把客服工单分类为 refund/technical/consult/complaint/other 之一. 只回一个英文词."},
            {"role": "user", "content": text[:1000]},
        ]
        client = LLMClient(provider=config.get("provider", "deepseek"))
        raw = (await client.chat(msgs, model=config.get("model"), temperature=0.0)).strip().lower()
        cat = raw.split()[0] if raw else "other"
        if cat not in {"refund", "technical", "consult", "complaint", "other"}:
            cat = "other"
        return {"category": cat, "confidence": 0.7, "by": "llm"}, 0.0

    def _retrieve(self, payload: dict, config: dict) -> tuple[Any, float]:
        self._ensure_kb(config)
        q = payload.get("query") or payload.get("text") or ""
        top_k = int(payload.get("top_k", 5))
        hits = _KB_SINGLETON.search(q, top_k=top_k)
        return {"query": q, "hits": hits, "kb_size": len(_KB_SINGLETON.docs)}, 0.0

    async def _auto_reply(
        self, payload: dict, config: dict
    ) -> tuple[Any, float]:
        self._ensure_kb(config)
        text = payload.get("text") or ""
        hits = _KB_SINGLETON.search(text, top_k=int(config.get("top_k", 4)))
        kb_block = "\n\n".join(
            f"[{h['id']} score={h['score']}]\n{h['snippet']}" for h in hits
        ) or "(无命中条目)"
        instr = (
            "你是「四面体电竞」客服助手. 根据下方知识库片段回答用户问题, "
            "不要编造未提到的政策. 语气兄弟向, 不油腻. 回复 ≤ 200 字.\n\n"
            f"知识库:\n{kb_block}\n\n用户问题:\n{text[:1500]}"
        )
        client = LLMClient(provider=config.get("provider", "deepseek"))
        reply = await client.chat(
            [
                {"role": "system", "content": "你是客服助手, 严守知识库."},
                {"role": "user", "content": instr},
            ],
            model=config.get("model"),
            temperature=0.3,
        )
        # 置信度 = top hit 的 BM25 score 归一 (粗略)
        top_score = hits[0]["score"] if hits else 0.0
        confidence = min(1.0, top_score / 5.0)
        threshold = float(config.get("auto_reply_threshold", 0.4))
        return {
            "reply": reply.strip(),
            "hits": hits,
            "confidence": round(confidence, 3),
            "auto_send": confidence >= threshold,
            "handoff": confidence < threshold,
        }, 0.0


__all__ = ["CRMAgent"]
