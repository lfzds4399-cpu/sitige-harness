"""pipelines — 5 条业务流水线编排.

每条 pipeline = N 个 stage, 顺序执行, manifest 持久化, validator 自动审核.

公开:
    Pipeline / Stage  抽象
    content_pipeline  内容生产 (5 stage)
    recruit_pipeline  工作室招募 (5 stage)
    match_pipeline    派单 (6 stage)
    crm_pipeline      客服 (4 stage)
    compliance_pipeline 合规审核 (3 stage)
    PIPELINES         {name -> Pipeline()} 注册表
"""
from __future__ import annotations

from tetra_harness.pipelines.base import Pipeline, Stage, StageResult, PipelineResult
from tetra_harness.pipelines.content_pipeline import ContentPipeline
from tetra_harness.pipelines.recruit_pipeline import RecruitPipeline
from tetra_harness.pipelines.match_pipeline import MatchPipeline
from tetra_harness.pipelines.crm_pipeline import CRMPipeline
from tetra_harness.pipelines.compliance_pipeline import CompliancePipeline


PIPELINES: dict[str, type[Pipeline]] = {
    "content": ContentPipeline,
    "recruit": RecruitPipeline,
    "match": MatchPipeline,
    "crm": CRMPipeline,
    "compliance": CompliancePipeline,
}


def get_pipeline(name: str) -> Pipeline:
    cls = PIPELINES.get(name)
    if cls is None:
        raise KeyError(f"unknown pipeline: {name!r}; choose from {list(PIPELINES)}")
    return cls()


__all__ = [
    "Pipeline", "Stage", "StageResult", "PipelineResult",
    "ContentPipeline", "RecruitPipeline", "MatchPipeline",
    "CRMPipeline", "CompliancePipeline",
    "PIPELINES", "get_pipeline",
]
