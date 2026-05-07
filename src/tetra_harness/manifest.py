"""manifest — 流水线阶段状态持久化.

每个 artifact (pipeline run) 一份 manifest.json, 记录各 stage 进度.
SKILL E2: pipeline 中断/重跑时按 manifest 决定从哪 stage 续跑.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

StageStatus = Literal["pending", "running", "done", "failed", "skipped"]

_VALID_STATUS: set[str] = {"pending", "running", "done", "failed", "skipped"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Manifest:
    """一个 artifact 的运行状态档."""

    def __init__(self, path: Path, artifact: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {
            "artifact": artifact or self.path.parent.name,
            "created_at": _now(),
            "updated_at": _now(),
            "stages": {},  # name -> {status, count, created_at, updated_at, ...meta}
        }
        if self.path.exists():
            self.load()

    # ---------- 持久化 ----------
    def load(self) -> dict[str, Any]:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 损坏直接重置 (manifest 不是源数据)
            pass
        return self.data

    def save(self) -> None:
        self.data["updated_at"] = _now()
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- 修改 ----------
    def update(
        self,
        stage: str,
        status: StageStatus,
        count: int = 0,
        **meta: Any,
    ) -> None:
        if status not in _VALID_STATUS:
            raise ValueError(f"invalid stage status: {status!r}")
        existing = self.data["stages"].get(stage, {})
        entry = {
            **existing,
            "status": status,
            "count": count,
            "updated_at": _now(),
            **meta,
        }
        if "created_at" not in entry:
            entry["created_at"] = _now()
        self.data["stages"][stage] = entry
        self.save()

    def get(self, stage: str) -> dict[str, Any] | None:
        return self.data["stages"].get(stage)

    def is_done(self, stage: str) -> bool:
        s = self.get(stage)
        return bool(s and s.get("status") == "done")

    # ---------- 渲染 ----------
    def summary(self) -> Any:
        """返回 rich.Table; 如未装 rich 则回退纯文本."""
        try:
            from rich.table import Table
        except ImportError:  # pragma: no cover
            lines = [f"manifest {self.data.get('artifact')}"]
            for name, s in self.data["stages"].items():
                lines.append(f"  {name:<20} {s.get('status'):<8} count={s.get('count', 0)}")
            return "\n".join(lines)

        t = Table(title=f"Manifest · {self.data.get('artifact')}", show_lines=False)
        t.add_column("Stage", style="bold")
        t.add_column("Status")
        t.add_column("Count", justify="right")
        t.add_column("Provider")
        t.add_column("Cost USD", justify="right")
        t.add_column("Updated", style="dim")

        color_map = {
            "pending": "yellow",
            "running": "cyan",
            "done": "green",
            "failed": "red",
            "skipped": "dim",
        }
        for name, s in self.data["stages"].items():
            status = s.get("status", "?")
            color = color_map.get(status, "white")
            cost = s.get("cost_usd")
            cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) else "-"
            t.add_row(
                name,
                f"[{color}]{status}[/{color}]",
                str(s.get("count", 0)),
                str(s.get("provider", "-")),
                cost_str,
                str(s.get("updated_at", "-")),
            )
        return t


def manifest_for(pipeline: str, root: Path | None = None) -> Manifest:
    """便捷构造: data/<pipeline>/manifest.json."""
    base = (root or Path("data")) / pipeline
    return Manifest(base / "manifest.json", artifact=pipeline)
