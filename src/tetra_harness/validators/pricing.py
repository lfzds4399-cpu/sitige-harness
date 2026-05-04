"""pricing — 5×5 分成矩阵价格合理性 + 单位经济模型交叉验证.

规则:
1. 默认抽成 + 工作室所得 = 100% (每业务)
2. 押金阶梯单调递增 (青铜 → 钻石)
3. 工作室等级返点单调非降 (0% → +5%)
4. 与 biz/单位经济模型.md 假设一致 (扣率落在合理区间)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import Validator, ValidationResult, safe_read


# 业务 → 期望平台抽成 (从 partners/pricing/分成结构.md)
EXPECTED_DEFAULT_TAKE_RATE = {
    "护航陪玩": 30,
    "代肝陪练": 30,
    "上分辅导": 35,
    "撞车": 25,
    "物资回收": 20,
}

# 等级单调递增
EXPECTED_TIERS = ["青铜", "白银", "黄金", "铂金", "钻石"]


def _parse_table_row(text: str, label: str) -> Optional[list[float]]:
    """从 markdown 表格抓某一行的数字 (按 | 切, 取百分比)."""
    for line in text.splitlines():
        if label in line and "|" in line:
            cells = [c.strip() for c in line.split("|")]
            nums = []
            for c in cells:
                # 抓 "70.0%" 或 "70%"
                m = re.search(r"(\d+(?:\.\d+)?)\s*%", c)
                if m:
                    nums.append(float(m.group(1)))
            if nums:
                return nums
    return None


def _check_total_100(text: str) -> list[tuple]:
    out = []
    for biz, expected in EXPECTED_DEFAULT_TAKE_RATE.items():
        # 找形如 "S1 | 护航陪玩 | 30% | 70%" 的行
        for line in text.splitlines():
            if biz in line and "|" in line:
                nums = re.findall(r"(\d+(?:\.\d+)?)\s*%", line)
                if len(nums) >= 2:
                    take = float(nums[0])
                    studio = float(nums[1])
                    if abs(take + studio - 100) < 0.01:
                        out.append(("ok", "PRICING_SUM_100",
                                    f"业务 '{biz}': 平台 {take}% + 工作室 {studio}% = 100%", ""))
                    else:
                        out.append(("error", "PRICING_SUM_BAD",
                                    f"业务 '{biz}': 平台 {take}% + 工作室 {studio}% ≠ 100%", ""))
                    if abs(take - expected) > 0.5:
                        out.append(("warn", "PRICING_RATE_DRIFT",
                                    f"业务 '{biz}': 实际抽成 {take}% ≠ 期望 {expected}%", ""))
                    break
    return out


def _check_tier_monotonic(text: str) -> list[tuple]:
    """5×5 矩阵每业务行 (青铜→钻石) 应单调非降."""
    out = []
    for biz in EXPECTED_DEFAULT_TAKE_RATE.keys():
        nums = _parse_table_row(text, biz)
        # 找含 5 个百分比的那一行 (即矩阵行)
        if nums and len(nums) >= 5:
            mat_row = nums[-5:]  # 最后 5 个百分比即为 5 等级
            non_decreasing = all(mat_row[i] <= mat_row[i + 1] + 0.01
                                 for i in range(len(mat_row) - 1))
            if non_decreasing:
                out.append(("ok", "PRICING_TIER_MONO",
                            f"业务 '{biz}' 5 等级单调递增: {mat_row}", ""))
            else:
                out.append(("error", "PRICING_TIER_BAD",
                            f"业务 '{biz}' 5 等级非单调: {mat_row}", ""))
    return out


def _check_deposit_monotonic(root: Path) -> list[tuple]:
    """押金机制 5 等级单调递增."""
    out = []
    text = safe_read(root / "partners/finance/押金机制.md")
    if not text:
        out.append(("warn", "DEPOSIT_DOC_MISSING", "押金机制.md 缺失或空", ""))
        return out
    # 找形如 "青铜 | ¥3000" 的行
    deposits = []
    for tier in EXPECTED_TIERS:
        for line in text.splitlines():
            if tier in line and ("¥" in line or "￥" in line or "元" in line):
                m = re.search(r"[¥￥]\s*(\d+(?:[,，]\d+)*)", line)
                if m:
                    deposits.append((tier, int(m.group(1).replace(",", "").replace("，", ""))))
                    break
    if len(deposits) >= 4:
        amounts = [d[1] for d in deposits]
        non_decreasing = all(amounts[i] <= amounts[i + 1]
                             for i in range(len(amounts) - 1))
        if non_decreasing:
            out.append(("ok", "DEPOSIT_MONO",
                        f"押金 {len(deposits)} 等级单调: {amounts}", ""))
        else:
            out.append(("error", "DEPOSIT_BAD",
                        f"押金非单调: {amounts}", ""))
    else:
        out.append(("warn", "DEPOSIT_PARTIAL",
                    f"押金阶梯仅识别 {len(deposits)}/5", ""))
    return out


def _check_unit_econ_consistency(root: Path) -> list[tuple]:
    """biz/单位经济模型.md 中提到的抽成应与 partners 一致."""
    out = []
    biz_text = safe_read(root / "biz/单位经济模型.md")
    if not biz_text:
        out.append(("warn", "UNIT_ECON_MISSING", "单位经济模型.md 缺失", ""))
        return out
    # 单位经济模型应提到主业务抽成 (任一)
    mention_rates = re.findall(r"(\d+)\s*%", biz_text)
    if any(int(r) in EXPECTED_DEFAULT_TAKE_RATE.values() for r in mention_rates):
        out.append(("ok", "UNIT_ECON_CONSISTENT",
                    "单位经济模型抽成假设与分成结构一致", ""))
    else:
        out.append(("warn", "UNIT_ECON_DRIFT",
                    "单位经济模型未明确引用 20-35% 抽成区间", ""))
    return out


class PricingValidator(Validator):
    name = "pricing"
    description = "5×5 分成矩阵 / 押金阶梯 / 单位经济模型 一致性校验"

    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            pricing_doc = project_root / "partners/pricing/分成结构.md"
            text = safe_read(pricing_doc)
            if not text:
                result.add("error", "PRICING_DOC_MISSING",
                           "partners/pricing/分成结构.md 不存在")
                return result

            for sev, code, msg, detail in _check_total_100(text):
                if sev == "ok":
                    result.add_ok(msg)
                else:
                    result.add(sev, code, msg, file=pricing_doc, detail=detail)

            for sev, code, msg, detail in _check_tier_monotonic(text):
                if sev == "ok":
                    result.add_ok(msg)
                else:
                    result.add(sev, code, msg, file=pricing_doc, detail=detail)

            for sev, code, msg, detail in _check_deposit_monotonic(project_root):
                if sev == "ok":
                    result.add_ok(msg)
                else:
                    result.add(sev, code, msg, detail=detail)

            for sev, code, msg, detail in _check_unit_econ_consistency(project_root):
                if sev == "ok":
                    result.add_ok(msg)
                else:
                    result.add(sev, code, msg, detail=detail)
        return result


__all__ = ["PricingValidator", "EXPECTED_DEFAULT_TAKE_RATE", "EXPECTED_TIERS"]
