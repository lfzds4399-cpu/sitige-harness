"""cost_tracker — LLM 调用成本累加 (JSON Lines).

写入 data/_costs/cost_log.jsonl, 单例累加. 用 .report() 出聚合.
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_LOG = Path("data/_costs/cost_log.jsonl")


class _CostTrackerImpl:
    """全局单例 — 进程内多 agent 累加同一份 jsonl."""

    def __init__(self, log_path: Path = DEFAULT_LOG):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def track(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usd: float = 0.0,
        **meta: Any,
    ) -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usd": float(usd),
            **meta,
        }
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def report(self, since: datetime | None = None) -> dict[str, Any]:
        """按 provider/model 聚合 usd / tokens."""
        if not self.log_path.exists():
            return {"total_usd": 0.0, "by_provider": {}, "by_model": {}, "records": 0}

        by_provider: dict[str, dict[str, float]] = defaultdict(
            lambda: {"usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0}
        )
        by_model: dict[str, dict[str, float]] = defaultdict(
            lambda: {"usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0}
        )
        total_usd = 0.0
        records = 0

        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since:
                    try:
                        ts = datetime.fromisoformat(r.get("ts", ""))
                        if ts < since:
                            continue
                    except (ValueError, TypeError):
                        pass
                provider = r.get("provider", "?")
                model = r.get("model", "?")
                usd = float(r.get("usd", 0.0))
                in_t = int(r.get("input_tokens", 0))
                out_t = int(r.get("output_tokens", 0))

                by_provider[provider]["usd"] += usd
                by_provider[provider]["input_tokens"] += in_t
                by_provider[provider]["output_tokens"] += out_t
                by_provider[provider]["calls"] += 1

                by_model[model]["usd"] += usd
                by_model[model]["input_tokens"] += in_t
                by_model[model]["output_tokens"] += out_t
                by_model[model]["calls"] += 1

                total_usd += usd
                records += 1

        return {
            "total_usd": round(total_usd, 4),
            "by_provider": {k: dict(v) for k, v in by_provider.items()},
            "by_model": {k: dict(v) for k, v in by_model.items()},
            "records": records,
        }


# 单例
CostTracker = _CostTrackerImpl()
