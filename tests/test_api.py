"""tests for tetra_harness.api — REST + WebSocket smoke + 401 + 404.

跑: pytest tests/test_api.py -x
"""
from __future__ import annotations

import os

import pytest

# 不预设 admin token, 确保 DEV 模式 (放行) 也工作
os.environ.pop("TETRA_ADMIN_TOKEN", None)


@pytest.fixture
def client(monkeypatch):
    """DEV 模式 client (无 admin token, 全放行)."""
    monkeypatch.delenv("TETRA_ADMIN_TOKEN", raising=False)
    from fastapi.testclient import TestClient

    from tetra_harness.api.server import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(monkeypatch):
    """带 admin token 的 client (PROD 模式)."""
    monkeypatch.setenv("TETRA_ADMIN_TOKEN", "test-secret-xyz")
    from fastapi.testclient import TestClient

    from tetra_harness.api.server import create_app

    app = create_app()
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-secret-xyz"})
    yield c


# ============================================================
# 基础: root + docs + auth
# ============================================================
def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    j = r.json()
    assert j["service"] == "tetra-harness-api"
    assert "ws" in j


def test_openapi(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Tetra Harness API"
    paths = schema["paths"]
    # 关键 routes 必在
    for must in [
        "/api/pipelines/",
        "/api/validators/",
        "/api/manifest/",
        "/api/runs/",
        "/api/auth/login",
    ]:
        assert must in paths, f"missing route: {must}"


def test_auth_login_dev_mode(client):
    """env 未配置时, login 任何 token 都通过."""
    r = client.post("/api/auth/login", json={"token": "anything"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_auth_login_prod_invalid(admin_client):
    # 直接调 login 用错 token
    bad = admin_client.post(
        "/api/auth/login",
        json={"token": "wrong-token"},
        headers={"Authorization": ""},
    )
    assert bad.status_code == 401


def test_auth_whoami_prod_no_token(admin_client):
    # 不带 header
    r = admin_client.get("/api/auth/whoami", headers={"Authorization": ""})
    assert r.status_code == 401


def test_auth_whoami_prod_ok(admin_client):
    r = admin_client.get("/api/auth/whoami")
    assert r.status_code == 200
    assert r.json()["mode"] == "prod"


# ============================================================
# pipelines
# ============================================================
def test_list_pipelines(client):
    r = client.get("/api/pipelines/")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) >= 5  # content / recruit / match / crm / compliance
    names = [p["name"] for p in items]
    assert "content" in names


def test_get_pipeline_404(client):
    r = client.get("/api/pipelines/notexist")
    assert r.status_code == 404


def test_get_pipeline_ok(client):
    r = client.get("/api/pipelines/content")
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "content"
    assert isinstance(j["stages"], list)


def test_run_pipeline_404(client):
    r = client.post("/api/pipelines/notexist/run", json={"config": {}, "async_mode": True})
    assert r.status_code == 404


# ============================================================
# validators
# ============================================================
def test_list_validators(client):
    r = client.get("/api/validators/")
    assert r.status_code == 200
    items = r.json()
    names = [v["name"] for v in items]
    # 至少 file_existence 必存在
    assert any("file" in n or "secret" in n or "compliance" in n for n in names)


def test_get_validator_404(client):
    r = client.get("/api/validators/notexist")
    assert r.status_code == 404


def test_query_findings_empty(client):
    r = client.get("/api/validators/findings?limit=10")
    assert r.status_code == 200
    j = r.json()
    assert "findings" in j
    assert "total" in j


def test_query_findings_severity_invalid(client):
    r = client.get("/api/validators/findings?severity=bogus")
    assert r.status_code == 422  # pydantic regex validation


# ============================================================
# manifest
# ============================================================
def test_list_manifests(client):
    r = client.get("/api/manifest/")
    assert r.status_code == 200
    j = r.json()
    assert "items" in j


def test_get_manifest_404(client):
    r = client.get("/api/manifest/__nonexistent__")
    assert r.status_code == 404


# ============================================================
# runs
# ============================================================
def test_list_runs_empty(client):
    r = client.get("/api/runs/?limit=10")
    assert r.status_code == 200
    j = r.json()
    assert "items" in j
    assert isinstance(j["items"], list)


def test_get_run_404(client):
    r = client.get("/api/runs/__nope__")
    assert r.status_code == 404


# ============================================================
# WebSocket
# ============================================================
def test_websocket_route_registered(client):
    """检查 /ws/pipelines/.../runs/... 路由已挂载.

    注: starlette TestClient 在 Python 3.14 上 websocket 有 disconnect 兼容问题
    (见 starlette issue), 这里用静态路由检查替代实际握手.
    """
    app = client.app
    paths = [getattr(r, "path", "") for r in app.routes]
    assert any("/ws/pipelines/" in p for p in paths)


# ============================================================
# 异步 run + WebSocket 集成 (mock pipeline)
# ============================================================
@pytest.mark.asyncio
async def test_run_pipeline_async_register():
    """单元测: register_run / finish_run 流程."""
    from tetra_harness.api.routes.runs import (
        finish_run,
        get_run,
        list_runs,
        new_run_id,
        register_run,
    )

    rid = new_run_id("content")
    rec = await register_run("content", run_id=rid)
    assert rec.status == "running"
    assert get_run(rid) is not None
    res = await finish_run(rid, status="done")
    assert res is not None
    assert res.status == "done"
    items = list_runs(pipeline="content", limit=20)
    assert any(r.run_id == rid for r in items)


@pytest.mark.asyncio
async def test_hub_publish_subscribe():
    from tetra_harness.api.websocket import HUB

    class _FakeWs:
        def __init__(self):
            self.msgs: list[str] = []

        async def send_text(self, t: str) -> None:
            self.msgs.append(t)

    ws = _FakeWs()
    history = await HUB.subscribe("rid-1", ws)
    assert isinstance(history, list)
    await HUB.publish("rid-1", {"pipeline": "content", "stage": "x", "status": "running"})
    assert any("running" in m for m in ws.msgs)
    await HUB.unsubscribe("rid-1", ws)
