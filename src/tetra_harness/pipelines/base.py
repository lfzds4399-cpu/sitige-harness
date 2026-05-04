"""pipelines.base — Pipeline / Stage 抽象.

设计:
- Stage 是一段 async 调用 (runner), 跑完写 manifest + 跑 validators.
- Pipeline 顺序执行 stages, 失败按 skip_on_error 决定继续/中断.
- Stage 间数据通过 ctx (dict) 传递, runner 读 ctx 写 ctx.
- only_stage 支持单 stage 重跑.

不依赖具体 LLM/HTTP, 仅编排. 业务 runner 各自 import agent.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from tetra_harness.manifest import Manifest, manifest_for

_log = logging.getLogger("tetra.pipeline")


# runner signature: async def(ctx, config) -> dict
StageRunner = Callable[[dict, dict], Awaitable[dict]]


@dataclass
class Stage:
    name: str
    runner: StageRunner
    validators: list[str] = field(default_factory=list)
    skip_on_error: bool = False
    cache: bool = True
    timeout_sec: float = 300.0


@dataclass
class StageResult:
    name: str
    ok: bool
    output: Any = None
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


@dataclass
class PipelineResult:
    pipeline: str
    ok: bool
    stages: list[StageResult] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "ok": self.ok,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "stages": [
                {
                    "name": s.name,
                    "ok": s.ok,
                    "elapsed_ms": round(s.elapsed_ms, 2),
                    "error": s.error,
                    "skipped_reason": s.skipped_reason,
                }
                for s in self.stages
            ],
        }


class Pipeline:
    """所有 pipeline 抽象基类.

    子类只需:
      - 设 name
      - 实现 build_stages(config) -> list[Stage]
      - 可选 default_payload 和 validators_for_stage 钩子
    """

    name: str = "base"
    description: str = ""

    def build_stages(self, config: dict) -> list[Stage]:
        raise NotImplementedError

    # ---- main entry ----
    async def run_all(
        self,
        config: dict,
        manifest: Optional[Manifest] = None,
        only_stage: Optional[str] = None,
        ctx: Optional[dict] = None,
    ) -> PipelineResult:
        """跑所有 stages (或仅 only_stage).

        ctx 是 stage 间共享 dict; 每个 runner 既读也写.
        manifest 为 None 时自动用 data/<pipeline>/manifest.json.
        """
        m = manifest or manifest_for(self.name)
        ctx = dict(ctx or {})
        ctx.setdefault("_pipeline", self.name)

        stages = self.build_stages(config)
        # 配置层 enabled=false 直接过滤
        stage_cfg_map: dict[str, dict] = {
            s.get("name", ""): s for s in (config.get("stages") or []) if isinstance(s, dict)
        }
        active_stages = [
            s for s in stages
            if stage_cfg_map.get(s.name, {}).get("enabled", True)
        ]
        if only_stage:
            active_stages = [s for s in active_stages if s.name == only_stage]
            if not active_stages:
                _log.warning("only_stage=%s 不在 pipeline %s, 无事可做", only_stage, self.name)

        results: list[StageResult] = []
        t0 = time.perf_counter()
        all_ok = True
        for stage in active_stages:
            sr = await self._run_one(stage, ctx, config, stage_cfg_map.get(stage.name, {}))
            results.append(sr)
            if not sr.ok and not stage.skip_on_error:
                all_ok = False
                _log.error("stage %s FAILED, abort pipeline %s", stage.name, self.name)
                m.update(stage.name, "failed", count=0, error=sr.error or "")
                break
            elif not sr.ok and stage.skip_on_error:
                _log.warning("stage %s failed but skip_on_error=true, 继续", stage.name)
                m.update(stage.name, "skipped", count=0, error=sr.error or "")
            else:
                count = self._count(sr.output)
                m.update(stage.name, "done", count=count)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return PipelineResult(
            pipeline=self.name, ok=all_ok, stages=results, elapsed_ms=elapsed_ms
        )

    # ---- per-stage ----
    async def _run_one(
        self,
        stage: Stage,
        ctx: dict,
        config: dict,
        stage_cfg: dict,
    ) -> StageResult:
        merged_cfg = {**config, **(stage_cfg.get("config") or {})}
        timeout = float(stage_cfg.get("timeout_sec", stage.timeout_sec))
        t0 = time.perf_counter()
        try:
            output = await asyncio.wait_for(stage.runner(ctx, merged_cfg), timeout=timeout)
        except asyncio.TimeoutError:
            return StageResult(
                name=stage.name, ok=False,
                error=f"timeout after {timeout}s",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except Exception as e:  # noqa: BLE001
            _log.exception("stage %s raised", stage.name)
            return StageResult(
                name=stage.name, ok=False,
                error=f"{type(e).__name__}: {e}",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )
        elapsed = (time.perf_counter() - t0) * 1000.0
        # 默认认为 dict-output 含 ok 字段时按其判定; 否则视为 ok
        ok = True
        if isinstance(output, dict) and "ok" in output:
            ok = bool(output["ok"])
        return StageResult(name=stage.name, ok=ok, output=output, elapsed_ms=elapsed)

    @staticmethod
    def _count(output: Any) -> int:
        """从 stage output 中提取一个 count 数字 (manifest 用)."""
        if isinstance(output, dict):
            for k in ("count", "total", "n"):
                v = output.get(k)
                if isinstance(v, int):
                    return v
            for k in ("topics", "candidates", "shots", "hits", "items", "rows", "results"):
                v = output.get(k)
                if isinstance(v, list):
                    return len(v)
        if isinstance(output, list):
            return len(output)
        return 0


__all__ = ["Pipeline", "Stage", "StageResult", "PipelineResult", "StageRunner"]
