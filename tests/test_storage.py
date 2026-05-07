"""storage 层测试.

覆盖:
- Database create_all + 4 model 增删改查
- InMemoryCache get/set/incr/exists/delete + ttl
- LocalArtifactStore put/get/list/delete round-trip
- EnvSecret / SopsSecret (mock subprocess) / CompositeSecret
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# 把 src/ 加到 sys.path
_HARNESS = Path(__file__).resolve().parent.parent
_SRC = _HARNESS / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------- 软依赖判定 ----------
try:
    import aiosqlite  # noqa: F401
    import sqlalchemy  # noqa: F401

    SQLA_OK = True
except Exception:
    SQLA_OK = False

skip_no_sqla = pytest.mark.skipif(not SQLA_OK, reason="sqlalchemy/aiosqlite 未装")


# ---------- import storage 不应炸 (即使依赖缺) ----------
def test_storage_modules_importable():
    from tetra_harness.storage import db, models, cache, artifact, secrets  # noqa

    assert db is not None
    assert models is not None
    assert cache is not None
    assert artifact is not None
    assert secrets is not None


# ---------- Database + models ----------
@skip_no_sqla
@pytest.mark.asyncio
async def test_database_crud(tmp_path):
    """Database create_all + 增删改查 4 model."""
    from tetra_harness.storage.db import Database
    from tetra_harness.storage.models import (
        AuditLog,
        CostEntry,
        Finding,
        Run,
        Stage,
        User,
        hash_token,
    )

    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    db = Database(url)
    await db.create_all()

    async with db.session() as s:
        # Run + Stage + Finding + CostEntry
        run = Run(pipeline="content", status="running", triggered_by="test")
        s.add(run)
        await s.flush()
        run_id = run.id

        stage = Stage(run_id=run_id, name="generate", status="running")
        s.add(stage)
        await s.flush()
        stage_id = stage.id

        f = Finding(
            run_id=run_id,
            stage_id=stage_id,
            validator="secret_scanner",
            severity="warn",
            code="leaked_token",
            message="possible token leak",
            file="x.py",
            line=10,
        )
        c = CostEntry(
            run_id=run_id,
            stage_id=stage_id,
            provider="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            usd=0.012,
        )
        u = User(
            username="lin",
            token_hash=hash_token("secret-token-xxx"),
            role="admin",
        )
        a = AuditLog(
            actor="lin",
            action="run.start",
            resource=run_id,
            payload={"pipeline": "content"},
            ip="127.0.0.1",
        )
        s.add_all([f, c, u, a])
        await s.commit()

    # 重新查
    from sqlalchemy import select

    async with db.session() as s:
        runs = (await s.execute(select(Run))).scalars().all()
        assert len(runs) == 1
        assert runs[0].pipeline == "content"

        stages = (await s.execute(select(Stage))).scalars().all()
        assert len(stages) == 1

        findings = (await s.execute(select(Finding))).scalars().all()
        assert len(findings) == 1
        assert findings[0].severity == "warn"

        users = (
            await s.execute(select(User).where(User.username == "lin"))
        ).scalars().all()
        assert len(users) == 1
        assert users[0].role == "admin"
        assert users[0].token_hash != "secret-token-xxx"  # hashed

        logs = (await s.execute(select(AuditLog))).scalars().all()
        assert len(logs) == 1
        assert logs[0].payload == {"pipeline": "content"}

    # 删 Run → 级联删 Stage / Finding / CostEntry
    async with db.session() as s:
        run = (await s.execute(select(Run))).scalars().first()
        await s.delete(run)
        await s.commit()

    async with db.session() as s:
        assert (await s.execute(select(Stage))).scalars().first() is None
        assert (await s.execute(select(Finding))).scalars().first() is None
        assert (await s.execute(select(CostEntry))).scalars().first() is None
        # User / AuditLog 不级联
        assert (await s.execute(select(User))).scalars().first() is not None
        assert (await s.execute(select(AuditLog))).scalars().first() is not None

    await db.close()


# ---------- InMemoryCache ----------
@pytest.mark.asyncio
async def test_inmemory_cache_basic():
    from tetra_harness.storage.cache import InMemoryCache

    c = InMemoryCache()
    assert await c.get("none") is None
    assert await c.exists("none") is False

    await c.set("a", {"x": 1})
    assert await c.get("a") == {"x": 1}
    assert await c.exists("a") is True

    await c.delete("a")
    assert await c.get("a") is None


@pytest.mark.asyncio
async def test_inmemory_cache_ttl():
    from tetra_harness.storage.cache import InMemoryCache

    c = InMemoryCache()
    await c.set("k", "v", ttl=1)
    assert await c.get("k") == "v"
    await asyncio.sleep(1.2)
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_inmemory_cache_incr():
    from tetra_harness.storage.cache import InMemoryCache

    c = InMemoryCache()
    assert await c.incr("counter") == 1
    assert await c.incr("counter", by=5) == 6
    assert await c.incr("counter") == 7


@pytest.mark.asyncio
async def test_get_cache_fallback_no_redis(monkeypatch):
    """REDIS_URL 空 → InMemoryCache."""
    from tetra_harness.storage import cache as cache_mod

    cache_mod.reset_cache()
    monkeypatch.delenv("REDIS_URL", raising=False)
    c = cache_mod.get_cache()
    assert isinstance(c, cache_mod.InMemoryCache)
    cache_mod.reset_cache()


# ---------- LocalArtifactStore ----------
@pytest.mark.asyncio
async def test_local_artifact_roundtrip(tmp_path):
    from tetra_harness.storage.artifact import LocalArtifactStore

    store = LocalArtifactStore(tmp_path / "art")
    url = await store.put("runs/r1/log.txt", b"hello world")
    assert url.startswith("file://")

    data = await store.get("runs/r1/log.txt")
    assert data == b"hello world"

    # list prefix
    keys = await store.list("runs/r1")
    assert "runs/r1/log.txt" in keys

    # presign url (本地 = file://)
    signed = await store.presign_url("runs/r1/log.txt", 60)
    assert signed.startswith("file://")

    # delete
    await store.delete("runs/r1/log.txt")
    keys2 = await store.list("runs/r1")
    assert "runs/r1/log.txt" not in keys2


@pytest.mark.asyncio
async def test_local_artifact_put_path(tmp_path):
    from tetra_harness.storage.artifact import LocalArtifactStore

    src = tmp_path / "src.txt"
    src.write_bytes(b"from path")

    store = LocalArtifactStore(tmp_path / "art2")
    await store.put("a/b.txt", src)
    data = await store.get("a/b.txt")
    assert data == b"from path"


@pytest.mark.asyncio
async def test_get_artifact_store_fallback_local(monkeypatch, tmp_path):
    """没 ARTIFACT_PROVIDER → local."""
    from tetra_harness.storage import artifact as art_mod

    art_mod.reset_artifact_store()
    monkeypatch.delenv("ARTIFACT_PROVIDER", raising=False)
    monkeypatch.setenv("ARTIFACT_LOCAL_PATH", str(tmp_path / "fallback"))
    s = art_mod.get_artifact_store()
    assert isinstance(s, art_mod.LocalArtifactStore)
    art_mod.reset_artifact_store()


# ---------- Secrets ----------
def test_env_secret(monkeypatch):
    from tetra_harness.storage.secrets import EnvSecret

    monkeypatch.setenv("MY_KEY", "abc123")
    s = EnvSecret()
    assert s.get("MY_KEY") == "abc123"
    assert s.get("NOT_THERE") is None
    assert s.get("NOT_THERE", "default") == "default"


def test_env_secret_with_prefix(monkeypatch):
    from tetra_harness.storage.secrets import EnvSecret

    monkeypatch.setenv("TETRA_X", "yes")
    s = EnvSecret(prefix="TETRA_")
    assert s.get("X") == "yes"


def test_sops_secret_file_missing(tmp_path):
    """文件不存在 → 空 dict, get 全 None, 不抛."""
    from tetra_harness.storage.secrets import SopsSecret

    s = SopsSecret(tmp_path / "ghost.enc.yaml")
    assert s.get("anything") is None


def test_sops_secret_decrypt_fail(monkeypatch, tmp_path):
    """sops 命令失败 (rc!=0) → 空 dict, 不抛."""
    from tetra_harness.storage import secrets as sec_mod

    fake = tmp_path / "f.enc.yaml"
    fake.write_text("encrypted")

    class FakeCP:
        def __init__(self):
            self.returncode = 1
            self.stdout = ""
            self.stderr = "fake fail"

    monkeypatch.setattr(sec_mod, "safe_run", lambda *a, **kw: FakeCP())
    s = sec_mod.SopsSecret(fake)
    assert s.get("any") is None


def test_sops_secret_decrypt_yaml_ok(monkeypatch, tmp_path):
    """sops 成功 → 解析 yaml + 嵌套路径."""
    from tetra_harness.storage import secrets as sec_mod

    fake = tmp_path / "f.enc.yaml"
    fake.write_text("encrypted")

    class FakeCP:
        def __init__(self):
            self.returncode = 0
            self.stdout = "openai_api_key: sk-fake\nanthropic:\n  key: ak-fake\n"
            self.stderr = ""

    monkeypatch.setattr(sec_mod, "safe_run", lambda *a, **kw: FakeCP())
    s = sec_mod.SopsSecret(fake)
    assert s.get("openai_api_key") == "sk-fake"
    assert s.get("anthropic.key") == "ak-fake"
    assert s.get("missing") is None


def test_composite_secret(monkeypatch):
    from tetra_harness.storage.secrets import CompositeSecret, EnvSecret

    class Fake:
        def __init__(self, d):
            self.d = d

        def get(self, k, default=None):
            return self.d.get(k, default)

    monkeypatch.setenv("FALLBACK_KEY", "from-env")
    monkeypatch.setenv("PRIMARY_KEY", "env-primary")

    primary = Fake({"PRIMARY_KEY": "from-sops"})
    composite = CompositeSecret([primary, EnvSecret()])

    assert composite.get("PRIMARY_KEY") == "from-sops"   # primary wins
    assert composite.get("FALLBACK_KEY") == "from-env"   # fallback to env
    assert composite.get("NOTHING") is None


def test_get_secrets_factory_default_env(monkeypatch):
    from tetra_harness.storage import secrets as sec_mod

    sec_mod.reset_secrets()
    monkeypatch.delenv("SECRETS_PROVIDER", raising=False)
    s = sec_mod.get_secrets()
    assert isinstance(s, sec_mod.EnvSecret)
    sec_mod.reset_secrets()
