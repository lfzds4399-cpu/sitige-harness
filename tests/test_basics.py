"""tests for tetra_harness 基建层 — pytest."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tetra_harness.logging_setup import setup_logging
from tetra_harness.manifest import Manifest, manifest_for
from tetra_harness.utils.cost_tracker import _CostTrackerImpl
from tetra_harness.utils.llm_client import PROVIDERS, LLMClient
from tetra_harness.utils.subprocess_safe import safe_run


# ============================================================
# logging_setup
# ============================================================
def test_setup_logging_quiet(tmp_path: Path):
    log = setup_logging(name="t-quiet", quiet=True, log_dir=tmp_path)
    # console handler level should be WARNING
    console_handlers = [
        h for h in logging.getLogger().handlers
        if not isinstance(h, logging.FileHandler)
    ]
    assert any(h.level == logging.WARNING for h in console_handlers)
    # 写盘
    assert hasattr(log, "log_path")
    assert Path(log.log_path).parent == tmp_path  # type: ignore[attr-defined]


def test_setup_logging_normal(tmp_path: Path):
    log = setup_logging(name="t-normal", quiet=False, log_dir=tmp_path)
    log.info("hello")
    log.warning("warn")
    # file handler 必须有
    file_handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) >= 1
    # 等 flush
    for fh in file_handlers:
        fh.flush()
    log_file = Path(log.log_path)  # type: ignore[attr-defined]
    content = log_file.read_text(encoding="utf-8")
    assert "warn" in content


# ============================================================
# Manifest
# ============================================================
def test_manifest_round_trip(tmp_path: Path):
    p = tmp_path / "m.json"
    m = Manifest(p, artifact="demo")
    m.update("step1", "running", count=0, provider="deepseek")
    m.update("step1", "done", count=42, provider="deepseek", cost_usd=0.0023)
    m.update("step2", "failed", error="boom")

    m2 = Manifest(p)
    assert m2.data["artifact"] == "demo"
    assert m2.is_done("step1")
    assert m2.get("step1")["count"] == 42
    assert m2.get("step2")["status"] == "failed"


def test_manifest_invalid_status(tmp_path: Path):
    m = Manifest(tmp_path / "m.json", artifact="demo")
    with pytest.raises(ValueError):
        m.update("s", "weird")  # type: ignore[arg-type]


def test_manifest_for_helper(tmp_path: Path):
    m = manifest_for("test_pipeline", root=tmp_path)
    assert m.path == tmp_path / "test_pipeline" / "manifest.json"


# ============================================================
# LLMClient — provider 切换 (不真调 API)
# ============================================================
def test_llm_provider_base_url():
    for prov, spec in PROVIDERS.items():
        c = LLMClient(provider=prov, api_key="dummy")  # type: ignore[arg-type]
        assert c.base_url == spec.base_url
        assert c.model == spec.default_model
        assert c.spec.api_key_env.endswith("API_KEY")


def test_llm_unsupported_provider():
    with pytest.raises(ValueError):
        LLMClient(provider="grok")  # type: ignore[arg-type]


def test_llm_from_env(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "dummy")
    c = LLMClient.from_env()
    assert c.provider == "qwen"
    assert "dashscope" in c.base_url


def test_llm_from_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "weird-provider")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy")
    c = LLMClient.from_env()
    assert c.provider == "deepseek"


# ============================================================
# CostTracker
# ============================================================
def test_cost_tracker_track_and_report(tmp_path: Path):
    log = tmp_path / "cost.jsonl"
    ct = _CostTrackerImpl(log_path=log)
    ct.track("deepseek", "deepseek-chat", 100, 50, 0.001)
    ct.track("deepseek", "deepseek-chat", 200, 80, 0.002)
    ct.track("qwen", "qwen-plus", 500, 200, 0.005)

    rep = ct.report()
    assert rep["records"] == 3
    assert pytest.approx(rep["total_usd"], rel=1e-6) == 0.008
    assert rep["by_provider"]["deepseek"]["calls"] == 2
    assert rep["by_provider"]["qwen"]["calls"] == 1
    # JSONL 真实写入
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    for ln in lines:
        json.loads(ln)  # 不抛即合法


# ============================================================
# safe_run
# ============================================================
def test_safe_run_success():
    import sys

    r = safe_run([sys.executable, "-c", "print('hello')"], timeout=10)
    assert r.returncode == 0
    assert "hello" in r.stdout


def test_safe_run_failure_logs_stderr_tail(caplog):
    import sys

    with caplog.at_level(logging.WARNING, logger="tetra.subprocess"):
        r = safe_run(
            [sys.executable, "-c", "import sys; sys.stderr.write('oops'); sys.exit(2)"],
            timeout=10,
        )
    assert r.returncode == 2
    # log 应包含 stderr tail
    msgs = " ".join(rec.message for rec in caplog.records)
    assert "rc=2" in msgs or "stderr" in msgs


def test_safe_run_timeout_returns_minus_one():
    import sys

    r = safe_run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=1,
    )
    assert r.returncode == -1
    assert "timeout" in (r.stderr or "")
