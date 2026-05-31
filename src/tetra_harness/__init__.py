"""tetra_harness — sitige-harness pipeline engineering runtime.

三层架构:
- agents/      业务逻辑 (LLM / 规则 / 外部 API 调用)
- validators/  审核规则 (audit 兼容 + 新规则)
- pipelines/   编排执行 (CLI 触发, manifest 持久化状态)

入口: `python -m tetra_harness` 或 `tetra` CLI.
"""
from __future__ import annotations

from tetra_harness._version import __version__

__all__ = ["__version__"]
