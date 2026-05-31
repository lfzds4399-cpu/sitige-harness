"""intel_agent — 社媒数据回收 / trend 扫描骨架.

⚠️ 当前为 mock 实现:
- 抖音/小红书 trending 公开 API 受限, 真接需对接 dataos / 蝉妈妈 / 新榜等付费平台.
- 本 agent 仅返回结构化 stub, 字段对齐真实 API, 方便后续替换.
- 自建爬虫存在合规/封号风险 (E2 教训), 不在此实现.

action:
  - scan_trends    : 拉热点/热词 (mock 返回 N 条)
  - scan_channels  : 招募渠道扫描 (QQ群/贴吧/虎扑/NGA/B站/Boss 等 stub)
  - dump_metrics   : 回收账号近 N 天数据 (mock)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any

from tetra_harness.agents.base import Agent, AgentResult

_log = logging.getLogger("tetra.agent.intel")

# 真实接入清单 (TODO 标记)
_TODO_APIS = {
    "douyin_trending": "dataos / 蝉妈妈 (付费)",
    "xhs_trending": "新红 / 灰豚 (付费)",
    "bilibili_trending": "B站开放平台 (申请)",
    "qq_groups": "QQ 群机器人 + 关键词监听",
    "tieba": "百度贴吧搜索 RSS",
    "hupu": "虎扑爬虫 (合规风险高)",
    "nga": "NGA 爬虫 (合规风险高)",
    "boss": "Boss 直聘 H5 (合规风险高)",
}


def _mock_trends(platform: str, n: int) -> list[dict[str, Any]]:
    keywords = [
        "tactical FPS", "extraction guide", "high-rank tips", "carry highlights",
        "studio recruit", "coaching diary", "weapon tips", "team tactics",
    ]
    return [
        {
            "rank": i + 1,
            "platform": platform,
            "keyword": random.choice(keywords),
            "heat": round(random.uniform(0.4, 1.0), 3),
            "delta_24h": round(random.uniform(-0.2, 0.5), 3),
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "source": "MOCK",
        }
        for i in range(n)
    ]


def _mock_channels(channels: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "channel": ch,
            "candidates_found": random.randint(2, 12),
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "todo_api": _TODO_APIS.get(ch, "需对接"),
            "source": "MOCK",
        }
        for ch in channels
    ]


class IntelAgent(Agent):
    name = "intel"
    description = "社媒/招募渠道数据回收 (当前为 mock)"

    async def run(self, payload: dict, config: dict) -> AgentResult:
        action = (payload or {}).get("action", "scan_trends")
        with self._timed() as box:
            try:
                if action == "scan_trends":
                    platforms = payload.get(
                        "platforms",
                        config.get("platforms", ["douyin", "xiaohongshu", "bilibili"]),
                    )
                    n_per = int(payload.get("limit", 5))
                    output = {p: _mock_trends(p, n_per) for p in platforms}
                elif action == "scan_channels":
                    channels = payload.get(
                        "channels",
                        config.get(
                            "channels",
                            ["qq_groups", "tieba", "hupu", "nga", "bilibili",
                             "boss", "douyin", "xiaohongshu"],
                        ),
                    )
                    output = {"results": _mock_channels(channels)}
                elif action == "dump_metrics":
                    days = int(payload.get("days", 7))
                    output = {
                        "since": (datetime.now() - timedelta(days=days)).date().isoformat(),
                        "rows": [
                            {
                                "date": (datetime.now() - timedelta(days=i)).date().isoformat(),
                                "follower_delta": random.randint(-3, 30),
                                "play_count": random.randint(500, 8000),
                                "engagement_rate": round(random.uniform(0.01, 0.08), 4),
                                "source": "MOCK",
                            }
                            for i in range(days)
                        ],
                    }
                else:
                    return self._fail(
                        f"unknown action: {action!r}", elapsed_ms=box["elapsed_ms"]
                    )
            except Exception as e:  # noqa: BLE001
                _log.exception("intel_agent failed")
                return self._fail(
                    f"{type(e).__name__}: {e}", elapsed_ms=box["elapsed_ms"]
                )
        # 标注 mock 状态, pipeline 上层可拦
        return self._ok(
            output=output,
            elapsed_ms=box["elapsed_ms"],
            mock=True,
            todo_apis=list(_TODO_APIS.keys()),
            action=action,
        )


__all__ = ["IntelAgent"]
