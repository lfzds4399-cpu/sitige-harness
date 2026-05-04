"""screen_agent — 实名/未保校验 (KYC).

⚠️ 真实接入需对接国家政务服务平台 / 公安实名核验 API (¥0.5/次).
当前为 mock: 18 位身份证仅做 校验位 + 年龄计算, 不做真核身.

action:
  - id_verify    : 身份证号 + 姓名 → 真实性 (mock: 校验位 + 年龄)
  - minor_check  : 年龄 < 18 拦截
  - blacklist    : 黑名单查 (本地 list, 可由 risk/黑名单管理.md 加载)
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from tetra_harness.agents.base import Agent, AgentResult

_log = logging.getLogger("tetra.agent.screen")

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def _id_card_valid(idn: str) -> bool:
    """二代居民身份证 18 位校验位.

    GB 11643-1999. 不做真实身份核验 (需公安 API).
    """
    if not idn or len(idn) != 18:
        return False
    body, last = idn[:17], idn[17].upper()
    if not body.isdigit():
        return False
    s = sum(int(c) * w for c, w in zip(body, _ID_WEIGHTS))
    return _ID_CHECK[s % 11] == last


def _id_card_age(idn: str) -> int:
    """从 18 位身份证算周岁."""
    try:
        y, m, d = int(idn[6:10]), int(idn[10:12]), int(idn[12:14])
        born = date(y, m, d)
    except (ValueError, IndexError):
        return -1
    today = date.today()
    age = today.year - born.year - (
        (today.month, today.day) < (born.month, born.day)
    )
    return age


def _load_blacklist(path: str | None) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.is_file():
        return set()
    out: set[str] = set()
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # 用空格/逗号/竖线第一段作为 ID
        token = line.split()[0].split(",")[0].split("|")[0].strip()
        if token:
            out.add(token)
    return out


class ScreenAgent(Agent):
    name = "screen"
    description = "KYC 实名 / 未成年保护 / 黑名单 (mock 实现)"

    async def run(self, payload: dict, config: dict) -> AgentResult:
        action = (payload or {}).get("action", "id_verify")
        with self._timed() as box:
            try:
                if action == "id_verify":
                    output = self._do_id_verify(payload, config)
                elif action == "minor_check":
                    output = self._do_minor_check(payload, config)
                elif action == "blacklist":
                    output = self._do_blacklist(payload, config)
                else:
                    return self._fail(
                        f"unknown action: {action!r}", elapsed_ms=box["elapsed_ms"]
                    )
            except Exception as e:  # noqa: BLE001
                _log.exception("screen_agent failed")
                return self._fail(
                    f"{type(e).__name__}: {e}", elapsed_ms=box["elapsed_ms"]
                )
        return self._ok(output=output, elapsed_ms=box["elapsed_ms"], mock=True, action=action)

    # ---- actions ----
    def _do_id_verify(self, payload: dict, config: dict) -> dict[str, Any]:
        idn = (payload.get("id_card") or "").replace(" ", "")
        name = payload.get("name", "")
        valid = _id_card_valid(idn)
        age = _id_card_age(idn) if valid else -1
        return {
            "id_card_masked": (idn[:6] + "*" * 8 + idn[-4:]) if len(idn) == 18 else "INVALID",
            "name": name,
            "valid_check_digit": valid,
            "age": age,
            "is_minor": valid and 0 <= age < 18,
            "passed": valid and age >= 18,
            "todo": "对接公安实名核验 API (¥0.5/次)",
        }

    def _do_minor_check(self, payload: dict, config: dict) -> dict[str, Any]:
        age = payload.get("age")
        if age is None:
            idn = (payload.get("id_card") or "").replace(" ", "")
            age = _id_card_age(idn) if _id_card_valid(idn) else -1
        threshold = int(config.get("minor_threshold", 18))
        is_minor = isinstance(age, int) and 0 <= age < threshold
        return {"age": age, "threshold": threshold, "is_minor": is_minor, "passed": not is_minor}

    def _do_blacklist(self, payload: dict, config: dict) -> dict[str, Any]:
        token = payload.get("token") or payload.get("id_card") or payload.get("user_id") or ""
        bl = _load_blacklist(config.get("blacklist_path"))
        hit = bool(token) and token in bl
        return {
            "token_masked": (token[:3] + "***" + token[-3:]) if len(token) >= 6 else token,
            "blacklist_size": len(bl),
            "hit": hit,
            "passed": not hit,
        }


__all__ = ["ScreenAgent"]
