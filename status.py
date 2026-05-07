#!/usr/bin/env python3
"""四面体电竞 · 项目状态薄壳.

优先调 `python -m tetra_harness status` (CLI 由基建 agent 提供).
基建 agent 还没接 status 命令时, fallback 到原版逻辑 (兼容).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Windows GBK 修复
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
HARNESS_SRC = Path(__file__).resolve().parent / "src"
if HARNESS_SRC.exists() and str(HARNESS_SRC) not in sys.path:
    sys.path.insert(0, str(HARNESS_SRC))


# 优先调 CLI; 失败 fallback 到原版渲染
def _try_cli() -> bool:
    try:
        pass  # type: ignore
    except Exception:
        return False
    try:
        # typer app 通常是 callable, 但安全起见用 subprocess 跑 -m
        env = os.environ.copy()
        env["PYTHONPATH"] = str(HARNESS_SRC) + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run(
            [sys.executable, "-m", "tetra_harness", "status"],
            cwd=str(ROOT), env=env, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


# ---- fallback (原版逻辑保留) ----
class C:
    R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    GOLD = "\033[38;2;255;215;0m"
    GRN = "\033[92m"; YEL = "\033[93m"; RED = "\033[91m"
    GRAY = "\033[90m"


def c(t, color):
    if not sys.stdout.isatty():
        return t
    return f"{color}{t}{C.R}"


def _fallback_main():
    print(c("\n╔═════════════════════════════════════════════════════════════════╗", C.GOLD))
    print(c("║  四面体电竞 · 项目状态                                           ║", C.B + C.GOLD))
    print(c("║  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            + "                                              ║", C.GRAY))
    print(c("╚═════════════════════════════════════════════════════════════════╝", C.GOLD))

    print()
    print(c("[模块] 文件统计", C.B + C.GOLD))
    print(c("─" * 70, C.GRAY))

    expected = ["brand", "web", "miniprogram", "app", "wechat", "bot", "server",
                "partners", "seller", "legal", "risk", "ops", "biz", "harness",
                "kook", "qq-channels"]
    for d in expected:
        p = ROOT / d
        if not p.is_dir():
            print(f"  {c('✗', C.RED)} {d:<14} {c('（不存在）', C.GRAY)}")
            continue
        files = [f for f in p.rglob("*")
                 if f.is_file() and "node_modules" not in str(f) and ".next" not in str(f)]
        size = sum(f.stat().st_size for f in files) / 1024
        n = len(files)
        if n == 0:
            print(f"  {c('·', C.GRAY)} {d:<14} 空")
        elif n < 5:
            print(f"  {c('⚠', C.YEL)} {d:<14} {c(str(n)+' 文件', C.YEL)}  {c(f'{size:.1f} KB', C.GRAY)}")
        else:
            print(f"  {c('✓', C.GRN)} {d:<14} {c(str(n)+' 文件', C.GRN)}  {c(f'{size:.1f} KB', C.GRAY)}")

    print()
    print(c("[核心 5 模块] 详细", C.B + C.GOLD))
    print(c("─" * 70, C.GRAY))
    for m in ["legal", "risk", "ops", "biz", "harness"]:
        p = ROOT / m
        if not p.is_dir():
            print(f"  {c('✗', C.RED)} {m}/ 不存在")
            continue
        for f in sorted(p.iterdir()):
            if f.is_file():
                size = f.stat().st_size / 1024
                print(f"    {c('·', C.GRAY)} {m}/{f.name:<35} {c(f'{size:>5.1f} KB', C.GRAY)}")

    print()
    print(c("[上次 audit]", C.B + C.GOLD))
    print(c("─" * 70, C.GRAY))
    audit = ROOT / "harness/last-audit.json"
    if audit.exists():
        try:
            data = json.loads(audit.read_text(encoding="utf-8"))
            print(f"  时间: {data.get('timestamp')}")
            t = data.get("total", {})
            print(f"  结果: {c(str(t.get('ok',0))+'✓', C.GRN)}  "
                  f"{c(str(t.get('warn',0))+'⚠', C.YEL)}  "
                  f"{c(str(t.get('fail',0))+'✗', C.RED)}")
            print(f"  整体: {data.get('overall', '-')}")
        except Exception as e:
            print(f"  {c('解析失败:', C.RED)} {e}")
    else:
        print(c("  尚无 audit 报告. 跑 `python harness/audit.py --json`", C.YEL))

    print()
    print(c("[快速命令]", C.B + C.GOLD))
    print(c("─" * 70, C.GRAY))
    print("  python harness/audit.py              # 全量审核")
    print("  python harness/audit.py --json       # 输出 JSON")
    print("  python harness/audit.py --module legal  # 单模块")
    print("  python harness/audit.py -v           # 详情")
    print("  python harness/status.py             # 当前状态（本命令）")
    print()


def main():
    if _try_cli():
        return
    _fallback_main()


if __name__ == "__main__":
    main()
