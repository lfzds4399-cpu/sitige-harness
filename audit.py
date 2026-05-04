#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四面体电竞 · Harness 一键审核 (薄壳).

内部走 tetra_harness.validators.file_existence + compliance + secret_scanner.
保持旧版输出兼容 (145✓ 0⚠ 0✗ 黑金风格 stdout) + last-audit.json.

用法:
    python harness/audit.py
    python harness/audit.py --module legal
    python harness/audit.py --json
    python harness/audit.py --strict
    python harness/audit.py -v
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# Windows GBK 修复
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 把 src/ 加 sys.path 以便直接 import (开发模式不依赖 pip install -e)
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tetra_harness.validators.file_existence import (  # noqa: E402
    ALL_CHECKS as FE_CHECKS,
)


# ---------- ANSI 黑金 ----------
class C:
    R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    RED = "\033[91m"; GRN = "\033[92m"; YEL = "\033[93m"
    GRAY = "\033[90m"
    GOLD = "\033[38;2;255;215;0m"


def _supports_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if sys.platform == "win32":
        try:
            os.system("")
        except Exception:
            pass
    return sys.stdout.isatty() or os.getenv("FORCE_COLOR") == "1"


USE_COLOR = _supports_color()


def c(text, color):
    return f"{color}{text}{C.R}" if USE_COLOR else text


OK = c("✓", C.GRN)
WARN = c("⚠", C.YEL)
FAIL = c("✗", C.RED)
INFO = c("·", C.GRAY)


# ---------- 兼容旧版 ModuleResult ----------
@dataclass
class _Finding:
    level: str
    msg: str
    detail: str = ""


@dataclass
class _ModuleResult:
    name: str
    findings: list = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def status(self):
        if any(f.level == "fail" for f in self.findings):
            return "fail"
        if any(f.level == "warn" for f in self.findings):
            return "warn"
        return "ok"

    @property
    def counts(self):
        d = {"ok": 0, "warn": 0, "fail": 0, "info": 0}
        for f in self.findings:
            d[f.level] += 1
        return d


def _sev_to_level(sev: str) -> str:
    """validator severity → 旧 level."""
    return {"ok": "ok", "warn": "warn", "error": "fail", "info": "info"}.get(sev, "info")


def _run_module(module_name: str, fn) -> _ModuleResult:
    m = _ModuleResult(name=module_name)
    t0 = time.time()
    try:
        items = fn(ROOT)
    except Exception as e:
        m.findings.append(_Finding("fail", f"{module_name} 模块异常: {e}"))
    else:
        for it in items:
            sev, code, msg, detail = it
            m.findings.append(_Finding(_sev_to_level(sev), msg, detail))
    m.elapsed_ms = (time.time() - t0) * 1000
    return m


# 模块名 → check 函数 dict
ALL_CHECKS = {name: fn for name, fn in FE_CHECKS}


def _render_module(mod: _ModuleResult, verbose: bool = False) -> None:
    icon = {"ok": OK, "warn": WARN, "fail": FAIL}[mod.status]
    cnt = mod.counts
    summary = f"{cnt['ok']}✓ {cnt['warn']}⚠ {cnt['fail']}✗"
    print(f"\n{icon} {c(mod.name.upper(), C.B + C.GOLD)}  "
          f"{c(summary, C.GRAY)}  {c(f'({mod.elapsed_ms:.0f}ms)', C.DIM)}")
    for f in mod.findings:
        if not verbose and f.level == "ok":
            continue
        sigil = {"ok": OK, "warn": WARN, "fail": FAIL, "info": INFO}[f.level]
        line = f"  {sigil} {f.msg}"
        if f.detail and (f.level in ("warn", "fail") or verbose):
            line += c(f"  → {f.detail}", C.GRAY)
        print(line)


def _render_summary(results: list[_ModuleResult]) -> tuple[str, dict]:
    print("\n" + c("━" * 70, C.GOLD))
    print(c("四面体电竞 · Harness 审核 — 总览", C.B + C.GOLD))
    print(c("━" * 70, C.GOLD))
    total = {"ok": 0, "warn": 0, "fail": 0}
    for r in results:
        cnt = r.counts
        total["ok"] += cnt["ok"]
        total["warn"] += cnt["warn"]
        total["fail"] += cnt["fail"]
        st_icon = {"ok": OK, "warn": WARN, "fail": FAIL}[r.status]
        st_color = {"ok": C.GRN, "warn": C.YEL, "fail": C.RED}[r.status]
        bar = c(f"{cnt['ok']:>2}✓ {cnt['warn']:>2}⚠ {cnt['fail']:>2}✗", st_color)
        print(f"  {st_icon} {r.name:<14} {bar}  {c(f'{r.elapsed_ms:>5.0f}ms', C.DIM)}")
    print(c("━" * 70, C.GOLD))
    print(f"  总计: {c(str(total['ok'])+'✓', C.GRN)}  "
          f"{c(str(total['warn'])+'⚠', C.YEL)}  "
          f"{c(str(total['fail'])+'✗', C.RED)}")
    overall = "fail" if total["fail"] else ("warn" if total["warn"] else "ok")
    msg = {"ok": "🟢 全部通过, 可上线",
           "warn": "🟡 有警告, 上线前过 checklist",
           "fail": "🔴 有错误, 必须修"}[overall]
    print(f"  {c(msg, {'ok': C.GRN, 'warn': C.YEL, 'fail': C.RED}[overall])}")
    print(c("━" * 70, C.GOLD) + "\n")
    return overall, total


def main() -> None:
    p = argparse.ArgumentParser(description="四面体电竞 harness audit (薄壳, 内部走 validators)")
    p.add_argument("--module", help="只跑某个模块: " + " / ".join(ALL_CHECKS))
    p.add_argument("--json", action="store_true", help="同时写 harness/last-audit.json")
    p.add_argument("--strict", action="store_true", help="warn 当 fail (CI exit 1)")
    p.add_argument("--verbose", "-v", action="store_true", help="显示所有 ok 项")
    args = p.parse_args()

    print(c("\n╔═════════════════════════════════════════════════════════════════╗", C.GOLD))
    print(c("║  四面体电竞 · 国内三角洲陪玩流量站 · Harness 审核                ║", C.B + C.GOLD))
    print(c("║  " + NOW + "                                              ║", C.GRAY))
    print(c("╚═════════════════════════════════════════════════════════════════╝", C.GOLD))

    if args.module and args.module not in ALL_CHECKS:
        print(f"{FAIL} 未知模块: {args.module}")
        sys.exit(2)

    targets = [args.module] if args.module else list(ALL_CHECKS.keys())
    results = [_run_module(name, ALL_CHECKS[name]) for name in targets]
    for r in results:
        _render_module(r, verbose=args.verbose)

    overall, total = _render_summary(results)

    if args.json or os.getenv("AUDIT_JSON"):
        out = {
            "timestamp": NOW,
            "overall": overall,
            "total": total,
            "modules": [
                {"name": r.name, "status": r.status, "elapsed_ms": r.elapsed_ms,
                 "counts": r.counts,
                 "findings": [asdict(f) for f in r.findings]}
                for r in results
            ],
        }
        out_path = ROOT / "harness/last-audit.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(c(f"  JSON 报告: {out_path}", C.GRAY) + "\n")

    if args.strict and (total["fail"] or total["warn"]):
        sys.exit(1)
    if total["fail"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
