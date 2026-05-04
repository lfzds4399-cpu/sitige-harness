"""manifest — 查 artifact 的 manifest 状态.

GET /api/manifest/                列出 data/ 下所有 artifact 名
GET /api/manifest/{artifact}      返 manifest 全文 (artifact / created_at / stages)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from tetra_harness.config import HARNESS_ROOT
from tetra_harness.manifest import Manifest, manifest_for

from ..schemas import ManifestResp
from .auth import get_admin

router = APIRouter()


def _data_root() -> Path:
    return HARNESS_ROOT / "data" if HARNESS_ROOT else Path("data")


@router.get("/")
def list_manifests(admin: dict = Depends(get_admin)) -> dict:
    root = _data_root()
    if not root.is_dir():
        return {"items": []}
    items = []
    for mp in sorted(root.glob("*/manifest.json")):
        try:
            m = Manifest(mp)
            items.append({
                "artifact": m.data.get("artifact"),
                "updated_at": m.data.get("updated_at"),
                "stage_count": len(m.data.get("stages", {})),
            })
        except Exception:  # noqa: BLE001
            continue
    return {"total": len(items), "items": items}


@router.get("/{artifact}", response_model=ManifestResp)
def get_manifest(artifact: str, admin: dict = Depends(get_admin)) -> dict:
    m = manifest_for(artifact, root=_data_root())
    if not m.path.exists():
        raise HTTPException(status_code=404, detail=f"manifest not found: {artifact}")
    return {
        "artifact": m.data.get("artifact", artifact),
        "created_at": m.data.get("created_at"),
        "updated_at": m.data.get("updated_at"),
        "stages": m.data.get("stages", {}),
    }


__all__ = ["router"]
