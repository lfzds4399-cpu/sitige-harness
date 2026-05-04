"""websocket — 实时 pipeline 进度推送.

进程内 broadcast (够用), 没引 redis 依赖.

路径:
    /ws/pipelines/{name}/runs/{run_id}

事件 JSON:
    {"ts": 1714368000.123, "run_id": "...", "pipeline": "content",
     "stage": "select_topic", "status": "running", "log": "..."}

挂载方式: setup_websocket(app) — 在 server.create_app() 里调一次.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, Optional

_log = logging.getLogger("tetra.api.ws")


class _Hub:
    """进程内 broadcast hub: run_id -> set[WebSocket].

    同时缓存最近 200 条事件, 新连接 onConnect 立刻 replay (省得错过早期事件).
    """

    def __init__(self, history: int = 200):
        self._channels: dict[str, set] = defaultdict(set)
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=history))
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str, ws: Any) -> list[dict]:
        async with self._lock:
            self._channels[run_id].add(ws)
            return list(self._history[run_id])

    async def unsubscribe(self, run_id: str, ws: Any) -> None:
        async with self._lock:
            self._channels.get(run_id, set()).discard(ws)

    async def publish(self, run_id: str, event: dict) -> None:
        event = {"ts": event.get("ts", time.time()), "run_id": run_id, **event}
        async with self._lock:
            self._history[run_id].append(event)
            subs = list(self._channels.get(run_id, set()))
        if not subs:
            return
        text = json.dumps(event, ensure_ascii=False)
        dead: list = []
        for ws in subs:
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._channels.get(run_id, set()).discard(ws)


HUB = _Hub()


def setup_websocket(app) -> None:
    """挂载 /ws/pipelines/{name}/runs/{run_id}."""
    try:
        from fastapi import WebSocket, WebSocketDisconnect
    except ImportError:  # pragma: no cover
        _log.warning("fastapi 缺失, websocket 不挂载")
        return

    @app.websocket("/ws/pipelines/{name}/runs/{run_id}")
    async def ws_pipeline_run(ws: WebSocket, name: str, run_id: str):  # noqa: D401
        await ws.accept()
        # replay 历史
        replay = await HUB.subscribe(run_id, ws)
        try:
            for evt in replay:
                await ws.send_text(json.dumps(evt, ensure_ascii=False))
            await ws.send_text(json.dumps({
                "ts": time.time(), "run_id": run_id,
                "pipeline": name, "status": "subscribed",
                "log": f"connected to run {run_id}",
            }, ensure_ascii=False))
            # 保持连接, 直到客户端断开
            while True:
                # 客户端主动 ping 或者关连接
                try:
                    msg = await ws.receive_text()
                    if msg == "ping":
                        await ws.send_text("pong")
                except WebSocketDisconnect:
                    break
                except Exception:
                    break
        finally:
            await HUB.unsubscribe(run_id, ws)


__all__ = ["HUB", "setup_websocket"]
