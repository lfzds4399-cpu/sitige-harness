"""cli — typer 标准命令: status / doctor / run / audit / upgrade / version-check / self-test."""
from __future__ import annotations

import asyncio
import importlib
import sys

import typer
from rich.console import Console
from rich.table import Table

from tetra_harness import __version__
from tetra_harness.config import (
    HARNESS_ROOT,
    get_env,
    list_configs,
    load_config,
)
from tetra_harness.logging_setup import setup_logging
from tetra_harness.manifest import Manifest, manifest_for
from tetra_harness.utils.subprocess_safe import safe_run

app = typer.Typer(
    name="tetra",
    help="sitige-harness — agents/validators/pipelines three-layer pipeline CLI",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


# Windows GBK 修复
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ============================================================
# tetra status
# ============================================================
@app.command(help="查看 manifest 状态 (各 pipeline 各 stage)")
def status(
    pipeline: str | None = typer.Option(None, "--pipeline", "-p", help="只看某 pipeline"),
) -> None:
    data_dir = HARNESS_ROOT / "data"
    if not data_dir.exists():
        console.print("[yellow]data/ 不存在, 还没跑过任何 pipeline[/yellow]")
        return

    if pipeline:
        m = manifest_for(pipeline, root=data_dir)
        if not m.path.exists():
            console.print(f"[red]找不到 manifest: {m.path}[/red]")
            raise typer.Exit(2)
        console.print(m.summary())
        return

    # 全量: 扫 data/*/manifest.json
    found = sorted(data_dir.glob("*/manifest.json"))
    if not found:
        console.print("[yellow]还没跑过任何 pipeline (data/*/manifest.json 为空)[/yellow]")
        return

    for p in found:
        m = Manifest(p)
        console.print(m.summary())
        console.print()


# ============================================================
# tetra doctor
# ============================================================
def _check(name: str, ok: bool, detail: str, fix: str = "") -> tuple[str, str, str, str, str]:
    sym = "[green]✓[/green]" if ok is True else "[yellow]⚠[/yellow]" if ok is None else "[red]✗[/red]"
    return (sym, name, detail, fix, "ok" if ok is True else ("warn" if ok is None else "fail"))


@app.command(help="系统健康检查 (依赖 / .env / 服务 / 工具)")
def doctor() -> None:
    rows: list[tuple[str, str, str, str, str]] = []

    # 1. Python 版本
    py_ok = sys.version_info >= (3, 10)
    rows.append(_check(
        "Python ≥ 3.11",
        py_ok,
        f"current {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "升级到 Python 3.11+",
    ))

    # 2. 依赖
    deps = ["typer", "rich", "yaml", "pydantic", "httpx", "openai", "tenacity", "dotenv"]
    for dep in deps:
        try:
            importlib.import_module(dep)
            rows.append(_check(f"pkg: {dep}", True, "installed", ""))
        except ImportError:
            pip_name = {"yaml": "pyyaml", "dotenv": "python-dotenv"}.get(dep, dep)
            rows.append(_check(
                f"pkg: {dep}",
                False,
                "MISSING",
                f"pip install {pip_name}",
            ))

    # 3. .env + 必填 key
    env_path = HARNESS_ROOT / ".env"
    rows.append(_check(
        ".env 文件",
        env_path.exists(),
        str(env_path),
        "复制 .env.example 为 .env 后填值",
    ))

    required_keys = [
        "DEEPSEEK_API_KEY",
        "POSTGRES_PASSWORD",
        "REDIS_HOST",
        "SERVER_PORT",
        "LLM_DEFAULT_PROVIDER",
    ]
    for k in required_keys:
        v = get_env(k)
        ok: bool | None
        if v:
            ok = True
            detail = "set"
        else:
            ok = None  # warn
            detail = "未设置"
        rows.append(_check(
            f"env: {k}",
            ok,
            detail,
            "在 .env 填入",
        ))

    # 4. 后端服务 healthz
    server_port = get_env("SERVER_PORT", "8001") or "8001"
    try:
        import httpx

        try:
            r = httpx.get(f"http://localhost:{server_port}/healthz", timeout=2.0)
            ok = r.status_code == 200
            rows.append(_check(
                f"server :{server_port}/healthz",
                ok if ok else None,
                f"http {r.status_code}",
                "启动 server: cd server && uvicorn app:app --port " + str(server_port),
            ))
        except Exception as e:
            rows.append(_check(
                f"server :{server_port}/healthz",
                None,
                f"unreachable ({type(e).__name__})",
                "启动 server: cd server && uvicorn app:app --port " + str(server_port),
            ))
    except ImportError:
        rows.append(_check(f"server :{server_port}/healthz", None, "httpx 未装跳过", ""))

    # 5. 数据库 (有密码才检, 否则跳过)
    if get_env("POSTGRES_PASSWORD"):
        r = safe_run(
            ["pg_isready", "-h", get_env("POSTGRES_HOST", "localhost") or "localhost",
             "-p", get_env("POSTGRES_PORT", "5432") or "5432"],
            timeout=5,
        )
        if r.returncode == 0:
            rows.append(_check("postgres", True, "ready", ""))
        elif r.returncode == 127:
            rows.append(_check("postgres", None, "pg_isready 未装", "装 postgresql-client"))
        else:
            rows.append(_check("postgres", None, f"rc={r.returncode}", "启动 postgres"))

    # 6. Redis
    if get_env("REDIS_HOST"):
        r = safe_run(
            ["redis-cli", "-h", get_env("REDIS_HOST", "localhost") or "localhost",
             "-p", get_env("REDIS_PORT", "6379") or "6379", "ping"],
            timeout=5,
        )
        if r.returncode == -1 and "timeout" in (r.stderr or ""):
            rows.append(_check("redis", None, "timeout", "启动 redis"))
        elif r.returncode == 0 and "PONG" in (r.stdout or ""):
            rows.append(_check("redis", True, "PONG", ""))
        else:
            rows.append(_check("redis", None, f"rc={r.returncode}", "启动 redis 或装 redis-cli"))

    # 7. 工具链
    for tool, hint in [
        ("git", "https://git-scm.com"),
        ("docker", "https://docker.com"),
        ("pandoc", "https://pandoc.org"),
    ]:
        r = safe_run([tool, "--version"], timeout=5)
        ok = r.returncode == 0
        ver = (r.stdout or "").splitlines()[0] if ok else "not found"
        rows.append(_check(f"tool: {tool}", ok if ok else None, ver, f"安装 {tool}: {hint}"))

    # 渲染
    t = Table(title=f"tetra doctor (v{__version__})", show_lines=False)
    t.add_column("", width=2)
    t.add_column("Check", style="bold")
    t.add_column("Detail")
    t.add_column("Fix", style="dim")

    n_ok = n_warn = n_fail = 0
    for sym, name, detail, fix, state in rows:
        t.add_row(sym, name, detail, fix)
        if state == "ok":
            n_ok += 1
        elif state == "warn":
            n_warn += 1
        else:
            n_fail += 1

    console.print(t)
    console.print()
    console.print(
        f"  汇总: [green]{n_ok}✓[/green]  [yellow]{n_warn}⚠[/yellow]  [red]{n_fail}✗[/red]"
    )
    if n_fail:
        console.print("  [red]有硬性失败项, 请按 Fix 列修复[/red]")
        raise typer.Exit(1)
    if n_warn:
        console.print("  [yellow]有 warn, 不阻断但建议处理[/yellow]")


# ============================================================
# tetra run <pipeline>
# ============================================================
@app.command(help="执行 pipeline (从 src/tetra_harness/pipelines/ 加载)")
def run(
    pipeline: str = typer.Argument(..., help="pipeline 名 (e.g. content_publish)"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="console 仅 WARNING+"),
    config: str | None = typer.Option(None, "--config", "-c", help="configs/<name>.yaml"),
    stage: str | None = typer.Option(None, "--stage", "-s", help="只跑指定 stage"),
) -> None:
    log_dir = HARNESS_ROOT / "logs"
    logger = setup_logging(name="tetra", quiet=quiet, log_dir=log_dir)

    cfg_name = config or pipeline
    try:
        cfg = load_config(cfg_name)
    except FileNotFoundError:
        console.print(
            f"[red]找不到 configs/{cfg_name}.yaml[/red]\n"
            f"可用 configs: {list_configs() or '(none)'}"
        )
        raise typer.Exit(2) from None

    # 动态 import pipelines.<pipeline>
    mod_name = f"tetra_harness.pipelines.{pipeline}"
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError:
        console.print(
            f"[red]pipeline 模块不存在: {mod_name}[/red]\n"
            "(pipelines agent 尚未交付; 基建层已就位等接入)"
        )
        raise typer.Exit(2) from None

    if not hasattr(mod, "run"):
        console.print(f"[red]{mod_name} 缺 run(config, stage=None, logger=None) 入口[/red]")
        raise typer.Exit(2)

    logger.info("pipeline=%s config=%s stage=%s", pipeline, cfg_name, stage or "(all)")
    try:
        mod.run(config=cfg, stage=stage, logger=logger)
    except Exception as e:
        logger.exception("pipeline 失败: %s", e)
        raise typer.Exit(1) from e


# ============================================================
# tetra audit
# ============================================================
@app.command(help="跑 validators/audit (兼容旧 audit.py 145 检查)")
def audit(
    validator: str | None = typer.Option(None, "--validator", "-v", help="只跑指定 validator"),
    report: bool = typer.Option(False, "--report", "-r", help="写 last-audit.json"),
    strict: bool = typer.Option(False, "--strict", help="warn 当 fail (CI 用)"),
) -> None:
    """通过 validators/audit 模块执行; 若该模块未交付, 回退到旧 harness/audit.py 兼容运行."""
    # 优先新 validators 实现
    try:
        mod = importlib.import_module("tetra_harness.validators.audit")
    except ModuleNotFoundError:
        mod = None

    if mod is not None and hasattr(mod, "run_audit"):
        cfg = load_config("audit")
        rc = mod.run_audit(config=cfg, validator=validator, report=report, strict=strict)
        raise typer.Exit(rc or 0)

    # ---- 回退到旧 harness/audit.py ----
    legacy = HARNESS_ROOT / "audit.py"
    if not legacy.exists():
        console.print("[red]validators/audit 未交付, 旧 audit.py 也找不到[/red]")
        raise typer.Exit(2)

    cmd = [sys.executable, str(legacy)]
    if validator:
        cmd += ["--module", validator]
    if report:
        cmd += ["--json"]
    if strict:
        cmd += ["--strict"]

    console.print(f"[dim]→ legacy fallback: {' '.join(cmd)}[/dim]")
    r = safe_run(cmd, timeout=120, cwd=HARNESS_ROOT.parent)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr and r.returncode != 0:
        sys.stderr.write(r.stderr)
    raise typer.Exit(r.returncode)


# ============================================================
# tetra version (彩蛋)
# ============================================================
@app.command(help="打印版本")
def version() -> None:
    console.print(f"tetra-harness v{__version__}")


# ============================================================
# tetra upgrade / version-check / self-test (Migrator + 自检)
# ============================================================
@app.command(help="自升级 harness 结构 (跑 pending migrations)")
def upgrade(
    target: str = typer.Option("latest", "--target", "-t", help="目标版本 (默认 latest)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只列计划, 不真跑"),
) -> None:
    from tetra_harness.migrations.migrator import Migrator

    project_root = HARNESS_ROOT.parent
    m = Migrator(project_root)
    pending = m.list_pending(target)

    if not pending:
        console.print(f"[green]✓ 已是最新 (current={m.current_version()})[/green]")
        return

    console.print(f"[yellow]Pending migrations: {len(pending)}[/yellow]")
    for mig in pending:
        console.print(f"  • {mig.from_version} → {mig.to_version}: {mig.description}")

    if dry_run:
        console.print("[dim](dry-run, 未真跑)[/dim]")
        return

    applied = asyncio.run(m.upgrade(target))
    console.print(f"[green]✓ 已应用 {len(applied)} 条; 当前版本 {m.current_version()}[/green]")


@app.command(name="version-check", help="检查是否有待升级的 migration")
def version_check() -> None:
    from tetra_harness.migrations.migrator import Migrator

    project_root = HARNESS_ROOT.parent
    m = Migrator(project_root)
    cur = m.current_version()
    pending = m.list_pending()
    console.print(f"current: [cyan]{cur}[/cyan]  ·  package: [cyan]{__version__}[/cyan]")
    if pending:
        console.print(f"[yellow]待升级 {len(pending)} 条[/yellow] (跑 [bold]tetra upgrade[/bold])")
        for mig in pending:
            console.print(f"  • {mig.from_version} → {mig.to_version}")
        raise typer.Exit(1)
    console.print("[green]✓ 已是最新[/green]")


@app.command(name="self-test", help="跑 SKILL self-audit 5 项 + 内部 invariants")
def self_test() -> None:
    """SKILL harness-engineering 五项自检 (E1-E5 教训对应)."""
    rows: list[tuple[str, str, str]] = []  # (sym, name, detail)

    # 1. 标准目录: configs/ data/ logs/ src/ tests/ docs/ 全在
    expect_dirs = ["configs", "data", "logs", "src", "tests", "docs"]
    missing = [d for d in expect_dirs if not (HARNESS_ROOT / d).exists()]
    if missing:
        rows.append(("[red]✗[/red]", "标准目录", f"缺: {missing}"))
    else:
        rows.append(("[green]✓[/green]", "标准目录", f"{len(expect_dirs)}/6 全在"))

    # 2. subprocess capture (E1) — utils/subprocess_safe.safe_run 存在
    try:
        from tetra_harness.utils import subprocess_safe as _ss
        ok = hasattr(_ss, "safe_run")
        rows.append(
            ("[green]✓[/green]" if ok else "[red]✗[/red]",
             "subprocess capture (E1)",
             "utils.subprocess_safe.safe_run" if ok else "缺 safe_run")
        )
    except ImportError:
        rows.append(("[red]✗[/red]", "subprocess capture (E1)", "utils.subprocess_safe 不存在"))

    # 3. quiet logging (E3) — logging_setup 含 quiet 形参
    try:
        import inspect

        from tetra_harness import logging_setup as _ls
        sig = inspect.signature(_ls.setup_logging)
        ok = "quiet" in sig.parameters
        rows.append(
            ("[green]✓[/green]" if ok else "[red]✗[/red]",
             "quiet logging (E3)",
             "setup_logging(quiet=...)" if ok else "缺 quiet 形参")
        )
    except (ImportError, AttributeError):
        rows.append(("[red]✗[/red]", "quiet logging (E3)", "logging_setup 缺失"))

    # 4. manifest 持久化 — manifest_for() 可调
    try:
        from tetra_harness.manifest import manifest_for as _mf
        ok = callable(_mf)
        rows.append(
            ("[green]✓[/green]" if ok else "[red]✗[/red]",
             "manifest 持久化",
             "manifest_for() 可调")
        )
    except ImportError:
        rows.append(("[red]✗[/red]", "manifest 持久化", "manifest 模块缺失"))

    # 5. tests/ 至少 1 个 test_*.py
    test_dir = HARNESS_ROOT / "tests"
    test_files = list(test_dir.glob("test_*.py")) if test_dir.exists() else []
    rows.append((
        "[green]✓[/green]" if test_files else "[red]✗[/red]",
        "tests 存在",
        f"{len(test_files)} 个 test_*.py" if test_files else "无",
    ))

    # 渲染
    t = Table(title="tetra self-test (SKILL E1-E5)", show_lines=False)
    t.add_column("", width=2)
    t.add_column("Check", style="bold")
    t.add_column("Detail", style="dim")
    n_ok = 0
    for sym, name, detail in rows:
        t.add_row(sym, name, detail)
        if "✓" in sym:
            n_ok += 1
    console.print(t)
    console.print(f"  [cyan]{n_ok}/{len(rows)}[/cyan] 通过")
    if n_ok < len(rows):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
