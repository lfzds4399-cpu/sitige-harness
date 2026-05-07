"""test_upgrade — Migrator 框架测试."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = HARNESS_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tetra_harness.migrations.migrator import (  # noqa: E402 — sys.path tweak above
    Migration,
    Migrator,
    _parse_semver,
)


# ============================================================
# semver 解析
# ============================================================
def test_parse_semver_normal() -> None:
    assert _parse_semver("1.2.3") == (1, 2, 3)
    assert _parse_semver("0.2.0") == (0, 2, 0)


def test_parse_semver_short() -> None:
    assert _parse_semver("1.0") == (1, 0, 0)
    assert _parse_semver("1") == (1, 0, 0)


def test_parse_semver_garbage() -> None:
    assert _parse_semver("abc") == (0, 0, 0)
    assert _parse_semver("") == (0, 0, 0)


# ============================================================
# Migrator: 干净仓库
# ============================================================
def test_current_version_default(tmp_path: Path) -> None:
    """没 .tetra-version 时, current = package version."""
    m = Migrator(tmp_path)
    cur = m.current_version()
    # 至少是合法 semver
    parts = _parse_semver(cur)
    assert parts != (0, 0, 0) or cur == "0.0.0"


def test_write_and_read_version(tmp_path: Path) -> None:
    m = Migrator(tmp_path)
    m.write_version("9.9.9")
    assert m.current_version() == "9.9.9"
    assert (tmp_path / ".tetra-version").read_text(encoding="utf-8").strip() == "9.9.9"


def test_list_pending_at_latest(tmp_path: Path) -> None:
    """假设当前已是 99.0.0, 没有 migration 能跨过去."""
    m = Migrator(tmp_path)
    m.write_version("99.0.0")
    pending = m.list_pending()
    assert pending == []


# ============================================================
# Fake migration round-trip
# ============================================================
class _FakeMigration(Migration):
    from_version = "99.0.0"
    to_version = "99.0.1"
    description = "test fake migration"

    ran_up = False
    ran_down = False

    async def up(self, project_root: Path) -> None:
        type(self).ran_up = True
        (project_root / "fake_marker.txt").write_text("up")

    async def down(self, project_root: Path) -> None:
        type(self).ran_down = True
        f = project_root / "fake_marker.txt"
        if f.exists():
            f.unlink()


def test_fake_migration_round_trip(tmp_path: Path) -> None:
    m = Migrator(tmp_path)
    m.write_version("99.0.0")
    # 注入假 migration
    m.migrations = [_FakeMigration()]
    pending = m.list_pending()
    assert len(pending) == 1
    assert pending[0].to_version == "99.0.1"

    # up
    _FakeMigration.ran_up = False
    applied = asyncio.run(m.upgrade("latest", dry_run=False))
    assert applied == ["99.0.1"]
    assert _FakeMigration.ran_up is True
    assert (tmp_path / "fake_marker.txt").exists()
    assert m.current_version() == "99.0.1"

    # down
    _FakeMigration.ran_down = False
    rolled = asyncio.run(m.rollback("99.0.0"))
    assert rolled == ["99.0.0"]
    assert _FakeMigration.ran_down is True
    assert not (tmp_path / "fake_marker.txt").exists()
    assert m.current_version() == "99.0.0"


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    m = Migrator(tmp_path)
    m.write_version("99.0.0")
    m.migrations = [_FakeMigration()]

    _FakeMigration.ran_up = False
    applied = asyncio.run(m.upgrade("latest", dry_run=True))
    assert applied == ["99.0.1"]  # 计划列出
    assert _FakeMigration.ran_up is False  # 但没真跑
    assert not (tmp_path / "fake_marker.txt").exists()
    assert m.current_version() == "99.0.0"  # 版本号不变


def test_v1_to_v2_loaded() -> None:
    """框架自带的 V1ToV2 应被 Migrator 自动发现."""
    m = Migrator(HARNESS_ROOT.parent)  # 项目根
    found_versions = {(mig.from_version, mig.to_version) for mig in m.migrations}
    assert ("0.1.0", "0.2.0") in found_versions
