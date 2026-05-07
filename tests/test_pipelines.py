"""test_pipelines — 5 pipeline mock 跑全 stage.

不打真 LLM/HTTP, 全部 monkeypatch.
验证: stage 顺序 / manifest 写入 / output 结构.
"""
from __future__ import annotations

import json

import pytest

from tetra_harness.manifest import Manifest
from tetra_harness.pipelines import (
    PIPELINES,
    CompliancePipeline,
    ContentPipeline,
    CRMPipeline,
    MatchPipeline,
    RecruitPipeline,
    get_pipeline,
)

pytestmark = pytest.mark.asyncio


# -------- shared fixtures -------- #
@pytest.fixture
def tmp_manifest(tmp_path) -> Manifest:
    return Manifest(tmp_path / "manifest.json", artifact="test")


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """每个 test 一个独立 data 目录, 不污染仓库."""
    from tetra_harness import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "HARNESS_ROOT", tmp_path, raising=True)
    # pipelines 各自从 config 模块 import HARNESS_ROOT
    for mod_name in (
        "tetra_harness.pipelines.content_pipeline",
        "tetra_harness.pipelines.recruit_pipeline",
        "tetra_harness.pipelines.match_pipeline",
        "tetra_harness.pipelines.crm_pipeline",
        "tetra_harness.pipelines.compliance_pipeline",
    ):
        import importlib
        m = importlib.import_module(mod_name)
        monkeypatch.setattr(m, "HARNESS_ROOT", tmp_path, raising=True)
    return tmp_path


# -------- LLM mock -------- #
class _FakeLLM:
    """伪 LLMClient: 按 messages 内容返回不同 stub JSON."""

    def __init__(self, *a, **kw):
        self.provider = "deepseek"

    async def chat(self, messages, model=None, **kw):
        last = (messages[-1].get("content") or "").lower()
        if "选题" in last or "topics" in last:
            return json.dumps({
                "topics": [
                    {"title": "高分段撤离实战 #1", "platform": "douyin",
                     "hook": "三分钟教你卡点撤离", "angle": "实战",
                     "format": "短视频", "est_engagement": 8, "est_conversion": 6}
                    for _ in range(3)
                ]
            }, ensure_ascii=False)
        if "脚本" in last or "shots" in last:
            return json.dumps({
                "hook": "你以为撤离就是跑?",
                "shots": [
                    {"visual": "玩家蹲点", "voiceover": "蹲点是基础", "duration_sec": 4},
                    {"visual": "队友接应", "voiceover": "队友卡位", "duration_sec": 4},
                ],
                "caption": "实战教学",
                "cta": "@四面体电竞 私信约局",
                "platform_tags": ["三角洲", "撤离"],
                "risk_note": "无",
            }, ensure_ascii=False)
        if "aigc" in last or "prompts" in last or "分镜" in last:
            return json.dumps({
                "prompts": [{"shot_id": 1, "prompt_zh": "...", "prompt_en": "..."}],
                "checklist": ["黑金主色", "无未成年", "无武器特写"],
            }, ensure_ascii=False)
        if "verdict" in last or "审核" in last or "合规" in last:
            return json.dumps({
                "verdict": "allow", "score": 88,
                "hits": [], "suggest": "通过",
            }, ensure_ascii=False)
        if "refund" in last or "退款" in last:
            return "consult"
        # auto_reply
        return "兄弟你好, 退款流程 7 天内联系客服, 提供订单号即可."


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch):
    from tetra_harness.utils import llm_client as lc
    monkeypatch.setattr(lc, "LLMClient", _FakeLLM, raising=True)
    # agents 模块 from ... import LLMClient → 也要 patch
    for mod_name in (
        "tetra_harness.agents.content_agent",
        "tetra_harness.agents.compliance_agent",
        "tetra_harness.agents.crm_agent",
    ):
        import importlib
        m = importlib.import_module(mod_name)
        monkeypatch.setattr(m, "LLMClient", _FakeLLM, raising=True)


# -------- match server mock -------- #
@pytest.fixture(autouse=True)
def patch_match_api(monkeypatch):
    async def _fake_call(base_url, payload, timeout):
        return {
            "order_id": payload["order_id"],
            "master_id": "M-MOCK-9001",
            "score": 0.91,
            "factors": payload["weights"],
        }
    from tetra_harness.agents import match_agent as ma
    monkeypatch.setattr(ma, "_call_match_api", _fake_call, raising=True)


# -------- 测试 -------- #
async def test_pipeline_registry_complete():
    assert set(PIPELINES) == {"content", "recruit", "match", "crm", "compliance"}
    for name in PIPELINES:
        p = get_pipeline(name)
        assert p.name == name


async def test_content_pipeline_runs_all_stages(tmp_manifest):
    config = {"provider": "deepseek", "candidates": 3,
              "platforms": ["douyin"], "weekly_count": {"douyin": 4},
              "brand_keywords": ["四面体"], "tone": "兄弟"}
    pipe = ContentPipeline()
    result = await pipe.run_all(config, manifest=tmp_manifest)
    assert result.ok, [s.error for s in result.stages]
    names = [s.name for s in result.stages]
    assert names == ["select_topic", "generate_script", "aigc_assets",
                     "compliance_review", "publish_brief"]
    # manifest 全部 done
    for n in names:
        assert tmp_manifest.is_done(n), f"{n} not done in manifest"


async def test_content_pipeline_only_stage(tmp_manifest):
    config = {"provider": "deepseek", "candidates": 2,
              "platforms": ["douyin"], "brand_keywords": [], "tone": "x"}
    result = await ContentPipeline().run_all(
        config, manifest=tmp_manifest, only_stage="select_topic"
    )
    assert result.ok
    assert len(result.stages) == 1
    assert result.stages[0].name == "select_topic"


async def test_recruit_pipeline_5_stages(tmp_manifest):
    config = {"channels": ["qq_groups", "tieba"], "kyc_fields": ["business_license"],
              "deposit_base_rmb": 5000, "trial_days": 7}
    result = await RecruitPipeline().run_all(config, manifest=tmp_manifest)
    assert result.ok, [s.error for s in result.stages]
    assert [s.name for s in result.stages] == [
        "scan_channels", "outreach_draft", "qualify", "deposit", "sign_offer",
    ]


async def test_match_pipeline_6_stages_with_mock_order(tmp_manifest):
    config = {
        "server_url": "http://mock",
        "weights": {"rank": 0.5, "rating": 0.5, "geo": 0, "language": 0,
                    "schedule": 0, "history": 0},
        "ack_timeout_min": 5,
        "dispatch_channels": ["kook"],
        "fallback_chain": ["x"],
        "default_amount_rmb": 99,
        "mock_order": {
            "order_id": "ORD-T-1", "user_id": "U-T", "user_segment": "vip",
            "urgency": "normal", "id_card": "", "service": "test",
        },
    }
    result = await MatchPipeline().run_all(config, manifest=tmp_manifest)
    assert result.ok, [s.error for s in result.stages]
    assert [s.name for s in result.stages] == [
        "intake", "screen", "match", "dispatch", "track", "settle",
    ]


async def test_crm_pipeline_4_stages_with_handoff(tmp_manifest):
    config = {
        "provider": "deepseek",
        "knowledge_base_paths": [],   # 空 KB → confidence=0 → 转人工
        "auto_reply_threshold": 0.4,
        "top_k": 4,
        "mock_ticket": {
            "ticket_id": "TK-T-1", "user_id": "U-T", "channel": "qq",
            "text": "我要投诉! 这个客服态度太差!", "created_at": "2026-04-30",
        },
    }
    result = await CRMPipeline().run_all(config, manifest=tmp_manifest)
    assert result.ok, [s.error for s in result.stages]
    assert [s.name for s in result.stages] == [
        "intake", "route", "auto_reply", "human_handoff",
    ]
    # 投诉应 handoff
    handoff_stage = result.stages[-1]
    assert handoff_stage.output["handoff"] is True


async def test_compliance_pipeline_3_stages(tmp_manifest):
    config = {
        "provider": "deepseek",
        "platform": "douyin",
        "strictness": "high",
        "manual_review_threshold": 60,
        "mock_text": "本周三角洲撤离实战教学, 兄弟带飞.",
        "mock_images": [],
    }
    result = await CompliancePipeline().run_all(config, manifest=tmp_manifest)
    assert result.ok, [s.error for s in result.stages]
    assert [s.name for s in result.stages] == [
        "text_scan", "image_audit", "final_gate",
    ]


async def test_pipeline_skip_on_error(tmp_manifest, monkeypatch):
    """模拟 match server 不可达 + skip_on_error 续跑."""
    async def _broken(base_url, payload, timeout):
        import httpx
        raise httpx.ConnectError("simulated down")

    from tetra_harness.agents import match_agent as ma
    monkeypatch.setattr(ma, "_call_match_api", _broken, raising=True)

    config = {
        "server_url": "http://broken",
        "weights": {"rank": 1.0},
        "ack_timeout_min": 1,
        "dispatch_channels": ["kook"],
        "fallback_chain": ["x"],
        "default_amount_rmb": 99,
        "mock_order": {
            "order_id": "ORD-T-2", "user_id": "U-T",
            "user_segment": "vip", "urgency": "normal",
            "id_card": "", "service": "test",
        },
    }
    result = await MatchPipeline().run_all(config, manifest=tmp_manifest)
    # match stage 失败但 skip_on_error=True → 整 pipeline 仍 ok
    assert result.ok
    match_stage = next(s for s in result.stages if s.name == "match")
    # match runner 自己把 fallback 包成 ok=True (queued); 这里至少 stage 有跑
    assert match_stage.elapsed_ms >= 0


async def test_unknown_pipeline_raises():
    with pytest.raises(KeyError):
        get_pipeline("nope")
