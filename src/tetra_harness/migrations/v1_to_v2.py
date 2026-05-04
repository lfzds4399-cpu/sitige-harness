"""v1 → v2 示例 migration.

场景: audit.py 旧版 945 行 → 薄壳 + validators/ 9 个.
此处把示例落实为 last-audit.json 路径迁移 (旧 harness/last-audit.json → data/audit/manifest.json),
不破坏现存 145✓ 体系.

特点:
  - 幂等 (跑两次不出错)
  - 安全 (旧文件原地保留, 只复制不删)
  - 校验 (validators/ 必须已存在; 否则报错)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .migrator import Migration

_log = logging.getLogger("tetra.migrator.v1_to_v2")


class V1ToV2(Migration):
    from_version = "0.1.0"
    to_version = "0.2.0"
    description = "audit.py 薄壳化 + last-audit.json → data/audit/manifest.json"

    async def up(self, project_root: Path) -> None:
        # 1. validators/ 必须已存在 (这一步在 v2 之前由 PR 完成)
        harness_root = project_root / "harness" if (project_root / "harness").exists() else project_root
        validators_dir = harness_root / "src" / "tetra_harness" / "validators"
        if not validators_dir.exists():
            raise RuntimeError(
                f"validators/ 不存在 ({validators_dir}); v2 结构未就绪, 拒绝升级"
            )

        # 2. 迁移 last-audit.json (如旧位置存在)
        old = harness_root / "last-audit.json"
        new_dir = harness_root / "data" / "audit"
        new = new_dir / "manifest.json"

        if old.exists() and not new.exists():
            new_dir.mkdir(parents=True, exist_ok=True)
            try:
                old_data = json.loads(old.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                _log.warning("旧 last-audit.json 解析失败, 跳过迁移: %s", e)
                return
            new.write_text(
                json.dumps(old_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _log.info("迁移 %s → %s", old, new)
        else:
            _log.info("last-audit.json 已迁移或不存在, 跳过")

    async def down(self, project_root: Path) -> None:
        """回滚 — 只删 data/audit/manifest.json (旧文件保留, 不删)."""
        harness_root = project_root / "harness" if (project_root / "harness").exists() else project_root
        new = harness_root / "data" / "audit" / "manifest.json"
        if new.exists():
            new.unlink()
            _log.info("已删 %s (旧 last-audit.json 保留)", new)
