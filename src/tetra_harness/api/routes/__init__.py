"""api.routes — REST 路由集合."""
from __future__ import annotations

from . import auth, manifest, pipelines, runs, validators

__all__ = ["auth", "pipelines", "validators", "manifest", "runs"]
