"""agents — 业务智能体层.

每个 agent 只做一件事 (LLM 调用 / 外部 API / 规则判断), 由 pipeline 编排.
统一抽象在 base.Agent / base.AgentResult.

公开 agent (按 module 名字 import):
    content_agent / intel_agent / match_agent /
    screen_agent / compliance_agent / crm_agent
"""
from __future__ import annotations

from tetra_harness.agents.base import Agent, AgentResult

__all__ = ["Agent", "AgentResult"]
