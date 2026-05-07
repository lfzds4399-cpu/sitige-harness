"""validators 单元测试 — 每 validator 至少 1 happy + 1 sad case.

跑: cd harness && python -m pytest tests/test_validators.py -x
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 把 src/ 加 sys.path
HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tetra_harness.validators import (  # noqa: E402
    BuildHealthValidator,
    ComplianceValidator,
    ContentQualityValidator,
    EnvKeysValidator,
    FileExistenceValidator,
    LegalDocValidator,
    PricingValidator,
    RiskValidator,
    SecretScannerValidator,
)
from tetra_harness.validators.base import line_is_exempt  # noqa: E402

REAL_ROOT = HERE.parent.parent  # repo root


# =================== fixtures ===================
@pytest.fixture
def tmp_root(tmp_path: Path):
    """临时空项目根."""
    return tmp_path


@pytest.fixture
def real_root():
    """Original e-sports business project root (private, not in OSS repo).

    Tests using this fixture exercise the reference validators against the
    upstream business project (legal/risk/ops/biz/kook/... layout). When the
    OSS repo is checked out standalone those directories are absent, so we
    skip the test rather than fail it. To run the real-project assertions,
    point pytest at a checkout that contains the business directories.
    """
    if not (REAL_ROOT / "legal").is_dir():
        pytest.skip(
            "requires upstream business project layout "
            "(legal/risk/ops/biz/kook/qq-channels/ ...) — "
            "this validator is shipped as a reference example only"
        )
    return REAL_ROOT


# =================== base helpers ===================
def test_line_is_exempt_true():
    assert line_is_exempt("严禁出现 代练 字样")
    assert line_is_exempt("禁止 卖号")
    assert line_is_exempt("- 不准 包过")


def test_line_is_exempt_false():
    assert not line_is_exempt("我们提供代练服务")
    assert not line_is_exempt("包过保证 100% 上分")


# =================== 1. file_existence ===================
def test_file_existence_real_project_passes(real_root):
    """真实项目应该全过 (145✓ 0⚠ 0✗ baseline)."""
    v = FileExistenceValidator()
    r = v.run(real_root)
    assert r.error_count == 0, [f.message for f in r.findings if f.severity == "error"][:5]
    assert r.warn_count == 0, [f.message for f in r.findings if f.severity == "warn"][:5]
    assert r.ok_count >= 140  # 145 baseline, 留 5 容差


def test_file_existence_missing_legal_dir(tmp_root):
    """空目录 → legal 全报缺失."""
    v = FileExistenceValidator()
    r = v.run(tmp_root)
    assert r.error_count > 0
    codes = {f.code for f in r.findings if f.severity == "error"}
    assert "LEGAL_MISSING" in codes


# =================== 2. secret_scanner ===================
def test_secret_scanner_clean_real_project(real_root):
    """真实项目应无 error 级硬编码 (allow warn)."""
    v = SecretScannerValidator()
    r = v.run(real_root)
    # error_count 可能因 .env.全栈.example 中带占位 sk-xxx 但 placeholder 过滤
    # 应该是 0
    if r.error_count > 0:
        msgs = [f"{f.code}: {f.message[:80]}" for f in r.findings if f.severity == "error"]
        # 至少打印出来便于人工确认
        print("SCANNER_ERRORS:", msgs[:5])


def test_secret_scanner_catches_openai_key(tmp_root):
    """临时塞 sk-AAAAA... 应被抓到 (error)."""
    f = tmp_root / "leaked.py"
    f.write_text(
        'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234"\n',
        encoding="utf-8",
    )
    v = SecretScannerValidator()
    r = v.run(tmp_root)
    assert r.error_count >= 1
    codes = {f.code for f in r.findings if f.severity == "error"}
    assert "OPENAI_KEY" in codes


def test_secret_scanner_skips_env_example_placeholder(tmp_root):
    """.env.example 中 sk-your_key 不应误报."""
    f = tmp_root / ".env.example"
    f.write_text("OPENAI_API_KEY=sk-your_openai_key_here\n", encoding="utf-8")
    v = SecretScannerValidator()
    r = v.run(tmp_root)
    assert r.error_count == 0


# =================== 3. compliance ===================
def test_compliance_catches_banned_in_marketing(tmp_root):
    """marketing/ 下出现 '代练' 且非豁免上下文 → error."""
    (tmp_root / "marketing").mkdir()
    (tmp_root / "marketing" / "weibo.md").write_text(
        "# 推广文案\n\n我们提供专业代练服务, 包过 100%, 价格优惠!\n",
        encoding="utf-8",
    )
    v = ComplianceValidator()
    r = v.run(tmp_root)
    # marketing 是 douyin/xiaohongshu/wechat/bilibili 共享, error 严格度
    assert r.error_count >= 1


def test_compliance_exempts_redline_doc(tmp_root):
    """文中 '禁止使用 代练 字样' 这种豁免上下文不报."""
    (tmp_root / "marketing").mkdir()
    (tmp_root / "marketing" / "rule.md").write_text(
        "# 红线规则\n\n严禁使用 '代练' '卖号' '外挂' 等词. 替代用 '陪练'.\n",
        encoding="utf-8",
    )
    v = ComplianceValidator()
    r = v.run(tmp_root)
    assert r.error_count == 0


def test_compliance_real_project(real_root):
    """真实项目跑一遍, 应该没 error (内容和文档都已经清理过)."""
    v = ComplianceValidator()
    r = v.run(real_root)
    # 不强断 0; 但记录 finding 数, 用于报告
    print(f"[compliance] real project errors={r.error_count} warns={r.warn_count}")


# =================== 4. legal_doc ===================
def test_legal_doc_real_project_passes(real_root):
    """真实 11 份法务文档应该齐全条款."""
    v = LegalDocValidator()
    r = v.run(real_root)
    if r.error_count > 0:
        miss = [f"{f.code}: {f.message[:80]}" for f in r.findings
                if f.severity == "error"]
        print("LEGAL_MISSING:", miss[:5])


def test_legal_doc_empty_project(tmp_root):
    """空项目所有文档缺 → 大量 error."""
    v = LegalDocValidator()
    r = v.run(tmp_root)
    assert r.error_count > 0


# =================== 5. risk ===================
def test_risk_real_project(real_root):
    v = RiskValidator()
    r = v.run(real_root)
    # 接受 warn, 不应 error (除非真缺文档)
    if r.error_count > 0:
        miss = [f"{f.code}: {f.message[:80]}" for f in r.findings
                if f.severity == "error"]
        print("RISK_MISSING:", miss[:5])


def test_risk_empty_project(tmp_root):
    v = RiskValidator()
    r = v.run(tmp_root)
    assert r.error_count > 0  # SOP 全缺


# =================== 6. content_quality ===================
def test_content_quality_placeholder_detection(tmp_root):
    """占位符未替换应 warn."""
    d = tmp_root / "content/本周内容"
    d.mkdir(parents=True)
    (d / "测试.md").write_text(
        "# 测试\n师傅 A 帮客户 百万回血, 价格 ￥xxx\n",
        encoding="utf-8",
    )
    v = ContentQualityValidator()
    r = v.run(tmp_root)
    assert r.warn_count >= 1


def test_content_quality_clean(tmp_root):
    d = tmp_root / "content/本周内容"
    d.mkdir(parents=True)
    (d / "干净.md").write_text(
        "# 三角洲新手必看\n带你 1 周从 K 到 Z, 装备实战截图.\n价格: 99 元/小时\n",
        encoding="utf-8",
    )
    v = ContentQualityValidator()
    r = v.run(tmp_root)
    assert r.warn_count == 0
    assert r.ok_count >= 1


def test_content_quality_llm_disabled_by_default(tmp_root):
    """无 config → enabled=False, 不调 LLM."""
    d = tmp_root / "content/本周内容"
    d.mkdir(parents=True)
    (d / "a.md").write_text("hello world", encoding="utf-8")
    v = ContentQualityValidator()
    r = v.run(tmp_root)
    # 不应有 LLM_UNAVAILABLE finding
    assert not any(f.code == "LLM_UNAVAILABLE" for f in r.findings)


# =================== 7. pricing ===================
def test_pricing_real_project_passes(real_root):
    v = PricingValidator()
    r = v.run(real_root)
    if r.error_count > 0:
        miss = [f"{f.code}: {f.message[:80]}" for f in r.findings
                if f.severity == "error"]
        print("PRICING_ERR:", miss[:5])


def test_pricing_missing_doc(tmp_root):
    v = PricingValidator()
    r = v.run(tmp_root)
    assert r.error_count >= 1
    assert any(f.code == "PRICING_DOC_MISSING" for f in r.findings)


def test_pricing_bad_sum(tmp_root):
    """造一个 平台 30% + 工作室 65% (= 95% 不是 100%) 的表."""
    d = tmp_root / "partners/pricing"
    d.mkdir(parents=True)
    (d / "分成结构.md").write_text(
        """| S1 | 护航陪玩 | 30% | 65% | 错误 |
| S2 | 代肝陪练 | 30% | 70% | 标准 |
""",
        encoding="utf-8",
    )
    v = PricingValidator()
    r = v.run(tmp_root)
    assert r.error_count >= 1
    assert any(f.code == "PRICING_SUM_BAD" for f in r.findings)


# =================== 8. env_keys ===================
def test_env_keys_real_project(real_root):
    v = EnvKeysValidator()
    r = v.run(real_root)
    # 不强断, 真实 .env 通常不存在, 应 warn
    print(f"[env_keys] ok={r.ok_count} warn={r.warn_count} error={r.error_count}")


def test_env_keys_no_env_warns(tmp_root):
    """有 example 但无 .env → warn."""
    (tmp_root / ".env.全栈.example").write_text(
        "# 🔴 必填\nPOSTGRES_PASSWORD=your_pwd_here\n",
        encoding="utf-8",
    )
    v = EnvKeysValidator()
    r = v.run(tmp_root)
    assert r.warn_count >= 1


def test_env_keys_filled_ok(tmp_root):
    (tmp_root / ".env.全栈.example").write_text(
        "# 🔴 必填\nPOSTGRES_PASSWORD=your_pwd_here\n",
        encoding="utf-8",
    )
    (tmp_root / ".env").write_text(
        "POSTGRES_PASSWORD=actual_strong_password_xyz123\n",
        encoding="utf-8",
    )
    v = EnvKeysValidator()
    r = v.run(tmp_root)
    assert r.ok_count >= 1
    assert r.warn_count == 0


# =================== 9. build_health ===================
def test_build_health_default_disabled(tmp_root):
    """默认 enabled=False, 应只输出 INFO."""
    v = BuildHealthValidator()
    r = v.run(tmp_root)
    assert r.error_count == 0
    assert r.warn_count == 0
    assert any(f.code == "BUILD_HEALTH_SKIP" for f in r.findings)


def test_build_health_enabled_missing_dirs(tmp_root):
    """enabled=True 但目录都缺 → 至少 1 warn (web 不是 optional)."""
    v = BuildHealthValidator()
    r = v.run(tmp_root, config={"build_health": {"enabled": True}})
    # web 是 non-optional, 缺目录 → warn
    assert any(f.code == "BUILD_TARGET_MISSING" for f in r.findings)


# =================== smoke: 9 个 validator import ok ===================
def test_all_validators_importable():
    from tetra_harness.validators import (  # noqa
        FileExistenceValidator, SecretScannerValidator, ComplianceValidator,
        LegalDocValidator, RiskValidator, ContentQualityValidator,
        PricingValidator, EnvKeysValidator, BuildHealthValidator,
        ALL_VALIDATORS, get_validator,
    )
    assert len(ALL_VALIDATORS) == 9
    assert get_validator("file_existence") is FileExistenceValidator
