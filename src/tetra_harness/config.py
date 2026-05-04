"""config — yaml + .env 配置加载.

configs/<name>.yaml 主配置, .env 注入环境变量 (python-dotenv).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

# 包根 = .../harness/src/tetra_harness ; 项目根 = .../harness
PKG_ROOT = Path(__file__).resolve().parent
HARNESS_ROOT = PKG_ROOT.parent.parent  # harness/
CONFIGS_DIR = HARNESS_ROOT / "configs"

_ENV_LOADED = False


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = HARNESS_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    _ENV_LOADED = True


def load_config(name: str, configs_dir: Optional[Path] = None) -> dict[str, Any]:
    """从 configs/<name>.yaml 加载配置, 同时确保 .env 已注入."""
    _load_env_once()
    base = configs_dir or CONFIGS_DIR
    path = base / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config {name}.yaml must be a mapping, got {type(data).__name__}")
    return data


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """读环境变量 (惰性加载 .env). None / 空串 都视为未设置."""
    _load_env_once()
    v = os.getenv(key, default)
    if v is None or v == "":
        return default
    return v


def list_configs(configs_dir: Optional[Path] = None) -> list[str]:
    base = configs_dir or CONFIGS_DIR
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.yaml"))
