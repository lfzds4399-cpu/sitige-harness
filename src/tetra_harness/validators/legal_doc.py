"""legal_doc — 11 份法务文档红线条款完整性检查.

每文档至少 5 个红线条款 (regex / keyword), 缺一即报.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import Validator, ValidationResult, safe_read


# 文档 → [(必含关键词组, 红线名)]  — 任一组命中即算条款齐
LEGAL_DOC_REQUIREMENTS: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "legal/用户服务条款.md": [
        (("信息撮合", "撮合服务", "服务定性"), "服务定性: 信息撮合"),
        (("管辖法院", "管辖", "法院"), "争议解决: 约定管辖"),
        (("仲裁", "争议", "调解"), "争议解决方式"),
        (("未成年", "18 周岁", "18周岁"), "未保拦截"),
        (("不可抗力",), "不可抗力条款"),
        (("单方", "变更", "通知"), "服务条款单方变更"),
    ],
    "legal/隐私政策.md": [
        (("个人信息保护法", "PIPL", "知情同意"), "PIPL 知情同意"),
        (("数据出境", "跨境", "境内"), "数据出境"),
        (("第三方", "共享", "委托"), "三方共享/委托处理"),
        (("Cookie", "cookie", "同类技术"), "Cookie 告知"),
        (("用户权利", "查阅", "更正", "删除"), "用户权利"),
    ],
    "legal/合作工作室协议.md": [
        (("独立承担", "独立法人"), "独立法律实体"),
        (("信息撮合",), "服务定性: 撮合"),
        (("税务", "纳税"), "独立税务责任"),
        (("押金",), "押金条款"),
        (("红线", "禁止"), "工作室红线"),
        (("解约", "终止", "解除"), "解约条款"),
    ],
    "legal/师傅签约协议.md": [
        (("与平台无关", "独立承担", "非劳动关系"), "非雇佣关系定性"),
        (("税务", "纳税"), "独立纳税责任"),
        (("反封号", "封号", "工具", "辅助"), "反封号承诺"),
        (("封号", "禁封"), "封号责任"),
        (("解约", "终止"), "解约条款"),
    ],
    "legal/退款仲裁规则.md": [
        (("场景 1", "场景一"), "退款场景 1"),
        (("场景 7", "场景七", "场景 6"), "退款场景 ≥6/7"),
        (("时效", "工作日", "小时"), "时效"),
        (("平台兜底", "兜底", "先行赔付"), "平台兜底"),
        (("仲裁", "调解"), "仲裁机制"),
    ],
    "legal/未成年人保护承诺.md": [
        (("18 周岁", "18周岁"), "年龄红线"),
        (("实名", "身份证"), "实名核验"),
        (("人脸", "刷脸", "活体"), "人脸校验"),
        (("健康系统", "防沉迷"), "防沉迷系统"),
        (("监护人", "家长"), "监护人渠道"),
    ],
    "legal/资金安全告知.md": [
        (("第三方支付", "持牌", "支付牌照"), "持牌支付"),
        (("反洗钱", "AML"), "反洗钱"),
        (("结算", "T+",), "结算周期"),
        (("退款", "争议"), "资金争议处理"),
    ],
    "legal/知识产权声明.md": [
        (("著作权", "版权"), "版权归属"),
        (("商标",), "商标"),
        (("UGC", "用户生成", "用户内容"), "UGC 内容授权"),
        (("侵权", "通知", "下架"), "侵权通知机制"),
    ],
    "legal/免责声明.md": [
        (("不可抗力",), "不可抗力"),
        (("第三方", "外部"), "第三方责任"),
        (("游戏官方", "厂商"), "游戏厂商免责"),
        (("封号", "禁封", "处罚"), "封号免责"),
    ],
    "legal/实名认证须知.md": [
        (("身份证",), "身份证核验"),
        (("人脸", "活体"), "活体校验"),
        (("18 周岁", "18周岁", "未成年"), "未保拦截"),
        (("公安", "二要素", "三要素"), "权威核验"),
    ],
    "legal/legal-checklist.md": [
        (("用户服务条款", "用户协议"), "checklist 含用户协议"),
        (("隐私政策", "隐私"), "checklist 含隐私"),
        (("退款", "仲裁"), "checklist 含退款"),
        (("未成年", "未保"), "checklist 含未保"),
    ],
}


def _doc_clause_check(root: Path, doc: str,
                      reqs: list[tuple[tuple[str, ...], str]]) -> list[tuple]:
    out = []
    text = safe_read(root / doc)
    if not text:
        out.append(("error", "LEGAL_DOC_MISSING", f"{doc} 不存在或为空", str(root / doc)))
        return out

    for kw_group, clause_name in reqs:
        if any(k in text for k in kw_group):
            out.append(("ok", "LEGAL_CLAUSE_OK",
                        f"[{doc}] 含 '{clause_name}'", ""))
        else:
            out.append(("error", "LEGAL_CLAUSE_MISSING",
                        f"[{doc}] 缺 '{clause_name}' (需含: {' / '.join(kw_group)})",
                        doc))
    return out


class LegalDocValidator(Validator):
    name = "legal_doc"
    description = "11 份法务文档红线条款 (每文档 ≥4 项必含条款)"

    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            for doc, reqs in LEGAL_DOC_REQUIREMENTS.items():
                items = _doc_clause_check(project_root, doc, reqs)
                for sev, code, msg, detail in items:
                    if sev == "ok":
                        result.add_ok(msg)
                    else:
                        f = project_root / doc if Path(doc).exists() or (project_root / doc).exists() else None
                        result.add(sev, code, msg, file=f, detail=detail)
        return result


__all__ = ["LegalDocValidator", "LEGAL_DOC_REQUIREMENTS"]
