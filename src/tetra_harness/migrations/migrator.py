"""migrator — harness 自升级核心.

设计:
  - Migration 抽象基类: from_version / to_version / up / down
  - Migrator: 扫描注册的 migrations, 比较 .tetra-version, 跑 pending
  - 状态文件: <project_root>/.tetra-version (text, 单行 semver)

调用:
    from pathlib import Path
    from tetra_harness.migrations import Migrator
    m = Migrator(Path.cwd())
    pending = m.list_pending()
    await m.upgrade("latest", dry_run=False)
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from tetra_harness._version import __version__ as CURRENT_VERSION  # noqa: N812

_log = logging.getLogger("tetra.migrator")

VERSION_FILE = ".tetra-version"


def _parse_semver(s: str) -> tuple[int, int, int]:
    """解析 'X.Y.Z' → (X, Y, Z); 不规范返 (0, 0, 0).

    跑 pending 顺序排序用; 不做严格验证.
    """
    parts = s.strip().split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return (0, 0, 0)


class Migration(ABC):
    """单步结构升级 (X.Y.Z → A.B.C).

    实现要求:
      - from_version / to_version / description 三个 ClassVar
      - up(project_root)  执行升级 (改文件 / 改结构 / 迁数据)
      - down(project_root) 回滚 (best-effort, 允许 NotImplemented)
    """

    from_version: ClassVar[str] = ""
    to_version: ClassVar[str] = ""
    description: ClassVar[str] = ""

    @abstractmethod
    async def up(self, project_root: Path) -> None:
        ...

    @abstractmethod
    async def down(self, project_root: Path) -> None:
        ...

    def __repr__(self) -> str:
        return f"<Migration {self.from_version}→{self.to_version}: {self.description}>"


class Migrator:
    """tetra upgrade 命令底层."""

    def __init__(self, project_root: Path) -> None:
        self.root = Path(project_root).resolve()
        self.migrations: list[Migration] = self._load_migrations()

    # ----- 装载 -----
    def _load_migrations(self) -> list[Migration]:
        """扫 tetra_harness.migrations 子模块, 收所有 Migration 子类."""
        from tetra_harness import migrations as pkg

        found: list[Migration] = []
        for _finder, name, _is_pkg in pkgutil.iter_modules(pkg.__path__):
            if name in ("migrator", "__init__"):
                continue
            try:
                mod = importlib.import_module(f"tetra_harness.migrations.{name}")
            except ImportError as e:
                _log.warning("跳过 migration 模块 %s: %s", name, e)
                continue

            for attr in dir(mod):
                cls = getattr(mod, attr)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, Migration)
                    and cls is not Migration
                ):
                    found.append(cls())

        # 按 from_version 排序; 实际链由 chain 计算
        found.sort(key=lambda m: _parse_semver(m.from_version))
        return found

    # ----- 状态 -----
    def current_version(self) -> str:
        """读项目根 .tetra-version; 没有则取 _version.CURRENT_VERSION."""
        f = self.root / VERSION_FILE
        if f.exists():
            v = f.read_text(encoding="utf-8").strip()
            if v:
                return v
        return CURRENT_VERSION

    def write_version(self, version: str) -> None:
        (self.root / VERSION_FILE).write_text(version + "\n", encoding="utf-8")

    # ----- 计划 -----
    def list_pending(self, target: str = "latest") -> list[Migration]:
        """从 current_version 出发, 按链路找到 target 的 migration 序列.

        target='latest' 表示一直跑到最末.
        """
        current = self.current_version()
        cur_t = _parse_semver(current)

        # 计算终点
        if target == "latest":
            if not self.migrations:
                return []
            end_t = max(_parse_semver(m.to_version) for m in self.migrations)
        else:
            end_t = _parse_semver(target)

        # 选出 from_version >= current 且 to_version <= end 的 migration
        pending = [
            m for m in self.migrations
            if _parse_semver(m.from_version) >= cur_t
            and _parse_semver(m.to_version) <= end_t
        ]
        return pending

    # ----- 执行 -----
    async def upgrade(self, target: str = "latest", dry_run: bool = False) -> list[str]:
        """跑 pending migrations; 返回已应用的 to_version 列表."""
        pending = self.list_pending(target)
        applied: list[str] = []
        if not pending:
            _log.info("已是最新, 无需升级")
            return applied

        for m in pending:
            _log.info("→ migration %s → %s: %s", m.from_version, m.to_version, m.description)
            if dry_run:
                applied.append(m.to_version)
                continue
            await m.up(self.root)
            self.write_version(m.to_version)
            applied.append(m.to_version)
        return applied

    async def rollback(self, to_version: str) -> list[str]:
        """回滚到指定版本 (倒序跑 down); best-effort."""
        cur_t = _parse_semver(self.current_version())
        target_t = _parse_semver(to_version)
        rolled: list[str] = []
        # 倒序选 from_version >= target 且 to_version <= current
        plan = sorted(
            [
                m for m in self.migrations
                if _parse_semver(m.to_version) <= cur_t
                and _parse_semver(m.from_version) >= target_t
            ],
            key=lambda m: _parse_semver(m.to_version),
            reverse=True,
        )
        for m in plan:
            _log.info("← rollback %s → %s", m.to_version, m.from_version)
            try:
                await m.down(self.root)
                self.write_version(m.from_version)
                rolled.append(m.from_version)
            except NotImplementedError:
                _log.warning("migration %s 不支持回滚, 跳过", m)
                break
        return rolled
