"""migrations — harness 自升级框架.

每条 migration 一个文件 (vX_to_vY.py), 实现 Migration 基类.
Migrator 自动扫描注册顺序应用; 状态写 .tetra-version.

不要直接调 migration; 用 `tetra upgrade` CLI.
"""
from __future__ import annotations

from .migrator import Migration, Migrator

__all__ = ["Migration", "Migrator"]
