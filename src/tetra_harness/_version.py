"""单点版本号 — pyproject.toml + __init__.py + 这里 三处保持同步.

使用约定:
  - MAJOR: 结构性升级 (跑 migration 才能用), 例如 v1→v2 的 audit.py 945 行薄壳化
  - MINOR: 加新模块 / 新 validator / 新 pipeline (向后兼容)
  - PATCH: bug fix / 文档 / 配置微调
"""
from __future__ import annotations

__version__ = "0.2.0"

# 历史里程碑 (Migrator 顺序按 from_version → to_version 链)
VERSION_HISTORY: list[tuple[str, str]] = [
    ("0.1.0", "初版 — agents/validators/pipelines 三层 + 145✓ audit"),
    ("0.2.0", "质量门禁 (ruff/mypy/bandit/coverage) + 文档站 + 自升级 Migrator"),
]
