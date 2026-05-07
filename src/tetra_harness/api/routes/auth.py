"""auth — admin token 鉴权.

最小可用:
- POST /api/auth/login  body {token} → 200 if env TETRA_ADMIN_TOKEN 匹配
- get_admin Depends → 任何 protected route 用 Depends(get_admin) 即可
- TETRA_ADMIN_TOKEN 未设时, 默认放行 (DEV 模式) 但响应头加 X-Auth-Mode: dev

不引入 jwt / oauth2, 单 token 设计够用 (内部工具).
"""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..schemas import LoginReq, LoginResp

router = APIRouter()


def _admin_token() -> str | None:
    return os.getenv("TETRA_ADMIN_TOKEN") or None


def get_admin(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Depends 守卫: 校验 Bearer 或 X-Admin-Token. 无 env 配置时 DEV 放行."""
    expected = _admin_token()
    if not expected:
        # DEV 模式: 不强校验, 但标记
        return {"role": "admin", "mode": "dev"}

    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_admin_token:
        token = x_admin_token.strip()

    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"role": "admin", "mode": "prod"}


@router.post("/login", response_model=LoginResp)
def login(req: LoginReq) -> LoginResp:
    expected = _admin_token()
    if not expected:
        # DEV: 任何 token 都能"登"
        return LoginResp(ok=True, role="admin")
    if not secrets.compare_digest(req.token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )
    return LoginResp(ok=True, role="admin")


@router.get("/whoami")
def whoami(admin: dict = Depends(get_admin)) -> dict:
    return admin


__all__ = ["router", "get_admin"]
