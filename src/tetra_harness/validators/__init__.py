"""tetra_harness.validators — 业务层验证规则.

每 validator 独立: import 简单, 互不依赖.

公开类:
- Validator / ValidationResult / Finding (抽象)
- FileExistenceValidator (145+ 项, 兼容 audit.py)
- SecretScannerValidator
- ComplianceValidator
- LegalDocValidator
- RiskValidator
- ContentQualityValidator
- PricingValidator
- EnvKeysValidator
- BuildHealthValidator
"""
from __future__ import annotations

from .base import (
    EXEMPT_CONTEXT_TOKENS,
    Finding,
    ValidationResult,
    Validator,
    iter_text_files,
    line_is_exempt,
    safe_read,
)
from .build_health import BuildHealthValidator
from .compliance import ComplianceValidator
from .content_quality import ContentQualityValidator
from .env_keys import EnvKeysValidator
from .file_existence import FileExistenceValidator
from .legal_doc import LegalDocValidator
from .pricing import PricingValidator
from .risk import RiskValidator
from .secret_scanner import SecretScannerValidator

# 默认全部 validator (build_health 默认 enabled=False, 由 config 控制)
ALL_VALIDATORS: list[type[Validator]] = [
    FileExistenceValidator,
    SecretScannerValidator,
    ComplianceValidator,
    LegalDocValidator,
    RiskValidator,
    ContentQualityValidator,
    PricingValidator,
    EnvKeysValidator,
    BuildHealthValidator,
]


def get_validator(name: str) -> type[Validator] | None:
    for v in ALL_VALIDATORS:
        if v.name == name:
            return v
    return None


__all__ = [
    "Finding", "ValidationResult", "Validator",
    "EXEMPT_CONTEXT_TOKENS", "line_is_exempt", "safe_read", "iter_text_files",
    "FileExistenceValidator", "SecretScannerValidator", "ComplianceValidator",
    "LegalDocValidator", "RiskValidator", "ContentQualityValidator",
    "PricingValidator", "EnvKeysValidator", "BuildHealthValidator",
    "ALL_VALIDATORS", "get_validator",
]
