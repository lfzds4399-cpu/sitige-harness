"""test_quality — 质量门禁元测试.

slow 测试需 dev extras (ruff/mypy/bandit). 跑:
  pytest tests/test_quality.py -m "not slow"   # 跳重型
  pytest tests/test_quality.py                 # 全跑
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = HARNESS_ROOT / "src" / "tetra_harness"


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    """走 utils.subprocess_safe.safe_run, 防 Windows GBK 炸 (E1)."""
    import sys
    sys.path.insert(0, str(SRC_DIR.parent))
    from tetra_harness.utils.subprocess_safe import safe_run

    r = safe_run(cmd, cwd=str(cwd), timeout=120)
    return r.returncode, r.stdout or "", r.stderr or ""


# ============================================================
# 元测试: 基础路径 (always run)
# ============================================================
def test_pyproject_exists() -> None:
    assert (HARNESS_ROOT / "pyproject.toml").exists()


def test_src_layout() -> None:
    assert SRC_DIR.exists()
    assert (SRC_DIR / "__init__.py").exists()
    assert (SRC_DIR / "_version.py").exists()


def test_version_consistent() -> None:
    """_version.py 与 __init__.py 必须导一致."""
    import importlib
    import sys
    if str(SRC_DIR.parent) not in sys.path:
        sys.path.insert(0, str(SRC_DIR.parent))
    from tetra_harness import __version__
    from tetra_harness._version import __version__ as v2
    assert __version__ == v2


def test_pyproject_extras_complete() -> None:
    import tomllib
    data = tomllib.loads((HARNESS_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    for k in ["dev", "api", "observability", "scheduling", "storage", "docs", "all"]:
        assert k in extras, f"缺 extra: {k}"


def test_ruff_config_present() -> None:
    import tomllib
    data = tomllib.loads((HARNESS_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "tool" in data
    assert "ruff" in data["tool"]
    assert "lint" in data["tool"]["ruff"]


def test_mypy_strict_overrides() -> None:
    """utils.* / manifest / config 必须 strict."""
    import tomllib
    data = tomllib.loads((HARNESS_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    overrides = data["tool"]["mypy"].get("overrides", [])
    found_strict_modules: set[str] = set()
    for o in overrides:
        if o.get("strict"):
            for m in o.get("module", []):
                found_strict_modules.add(m)
    assert "tetra_harness.utils.*" in found_strict_modules
    assert "tetra_harness.manifest" in found_strict_modules
    assert "tetra_harness.config" in found_strict_modules


# ============================================================
# 重型: ruff / mypy / bandit (装了 dev extras 才跑)
# ============================================================
@pytest.mark.slow
def test_ruff_clean() -> None:
    if not shutil.which("ruff"):
        pytest.skip("ruff 未装; pip install -e '.[dev]'")
    rc, out, err = _run(["ruff", "check", "src/"], cwd=HARNESS_ROOT)
    assert rc == 0, f"ruff 报错:\n{out}\n{err}"


@pytest.mark.slow
def test_mypy_utils_strict() -> None:
    if not shutil.which("mypy"):
        pytest.skip("mypy 未装; pip install -e '.[dev]'")
    rc, out, err = _run(
        ["mypy", "src/tetra_harness/utils/"],
        cwd=HARNESS_ROOT,
    )
    assert rc == 0, f"mypy strict utils 失败:\n{out}\n{err}"


@pytest.mark.slow
def test_bandit_clean() -> None:
    if not shutil.which("bandit"):
        pytest.skip("bandit 未装; pip install -e '.[dev]'")
    rc, out, err = _run(
        ["bandit", "-r", "src/", "-q", "-ll"],  # only HIGH severity
        cwd=HARNESS_ROOT,
    )
    # bandit return 1 if issues found, 0 if clean
    assert rc == 0, f"bandit 高危发现:\n{out}\n{err}"
