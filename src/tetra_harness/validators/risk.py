"""risk — 11 份风控 SOP 完整性 + 实名/未保/资金/反封号红线检查."""
from __future__ import annotations

from pathlib import Path

from .base import ValidationResult, Validator, safe_read

# 11 份 SOP 必含条款
RISK_DOC_REQUIREMENTS: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "risk/实名审核 SOP.md": [
        (("身份证", "二要素", "三要素"), "身份证核验"),
        (("18", "18 位", "校验位", "校验码"), "身份证 18 位/校验位"),
        (("人脸", "活体", "刷脸"), "人脸活体"),
        (("公安", "权威源", "OCR"), "权威源核验"),
    ],
    "risk/未成年识别 SOP.md": [
        (("18 周岁", "18周岁", "未成年"), "年龄红线"),
        (("拦截", "禁止", "下单"), "拦截动作"),
        (("监护人", "家长"), "监护人渠道"),
        (("健康系统", "防沉迷"), "防沉迷"),
    ],
    "risk/反封号 SOP.md": [
        (("设备指纹", "设备", "指纹"), "设备指纹"),
        (("IP",), "IP 隔离/管理"),
        (("脚本", "外挂", "辅助"), "脚本/外挂禁用"),
        (("行为", "异常"), "异常行为监控"),
    ],
    "risk/资金安全 SOP.md": [
        (("T+", "结算"), "T+N 结算"),
        (("第三方支付", "持牌"), "持牌支付"),
        (("反洗钱", "AML", "可疑"), "反洗钱"),
        (("退款", "争议"), "资金争议处理"),
    ],
    "risk/投诉仲裁 SOP.md": [
        (("时效", "工作日"), "时效"),
        (("升级", "二线"), "升级机制"),
        (("证据",), "证据收集"),
    ],
    "risk/危机公关 SOP.md": [
        (("舆情", "媒体"), "舆情监测"),
        (("声明", "回应"), "声明发布"),
        (("升级", "上报"), "升级路径"),
    ],
    "risk/黑名单管理.md": [
        (("入库", "拉黑", "封禁"), "入库流程"),
        (("申诉", "解除"), "申诉/解除"),
        (("跨平台", "共享"), "跨业务共享"),
    ],
    "risk/合作工作室风控.md": [
        (("KPI", "考核"), "KPI"),
        (("淘汰", "退出"), "淘汰机制"),
        (("押金",), "押金"),
    ],
    "risk/平台关键词审核表.md": [
        (("抖音",), "抖音规则"),
        (("小红书",), "小红书规则"),
        (("代练", "卖号", "外挂"), "红线词列表"),
        (("替换", "改写", "替代"), "改写建议"),
    ],
    "risk/数据安全 SOP.md": [
        (("加密", "脱敏"), "加密/脱敏"),
        (("等保", "PIPL", "个人信息保护法"), "合规依据"),
        (("权限", "最小化"), "权限最小化"),
        (("审计", "日志"), "审计日志"),
    ],
    "risk/应急预案.md": [
        (("宕机", "故障"), "技术故障"),
        (("回滚", "恢复"), "回滚/恢复"),
        (("通报", "升级"), "升级通报"),
    ],
}


def _check_doc(root: Path, doc: str,
               reqs: list[tuple[tuple[str, ...], str]]) -> list[tuple]:
    out = []
    text = safe_read(root / doc)
    if not text:
        out.append(("error", "RISK_DOC_MISSING", f"{doc} 不存在或为空", doc))
        return out
    for kw_group, name in reqs:
        if any(k in text for k in kw_group):
            out.append(("ok", "RISK_CLAUSE_OK", f"[{doc}] 含 '{name}'", ""))
        else:
            out.append(("warn", "RISK_CLAUSE_MISSING",
                        f"[{doc}] 缺 '{name}' (需含: {' / '.join(kw_group)})", doc))
    return out


class RiskValidator(Validator):
    name = "risk"
    description = "11 风控 SOP 红线条款检查 (实名 18 位/未保拦截/T+N/设备指纹)"

    def run(self, project_root: Path, config: dict | None = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            for doc, reqs in RISK_DOC_REQUIREMENTS.items():
                for sev, code, msg, detail in _check_doc(project_root, doc, reqs):
                    if sev == "ok":
                        result.add_ok(msg)
                    else:
                        result.add(sev, code, msg,
                                   file=(project_root / doc) if (project_root / doc).is_file() else None,
                                   detail=detail)

            # 跨文档红线: 实名 SOP 必须含身份证 18 位校验
            kyc = safe_read(project_root / "risk/实名审核 SOP.md")
            if "18 位" in kyc or "18位" in kyc or "校验位" in kyc or "校验码" in kyc:
                result.add_ok("跨文档: 实名 SOP 含身份证 18 位/校验位逻辑")
            else:
                result.add("warn", "RISK_KYC_18DIGIT",
                           "实名 SOP 未明确身份证 18 位校验",
                           file=project_root / "risk/实名审核 SOP.md")

            # 资金安全 SOP 含 T+N
            fund = safe_read(project_root / "risk/资金安全 SOP.md")
            if "T+" in fund:
                result.add_ok("跨文档: 资金安全 SOP 含 T+N 结算")
            else:
                result.add("warn", "RISK_FUND_TPN",
                           "资金安全 SOP 未提 T+N 结算")

            # 反封号 SOP 含设备指纹/IP 隔离
            anti = safe_read(project_root / "risk/反封号 SOP.md")
            if ("设备" in anti or "指纹" in anti) and "IP" in anti:
                result.add_ok("跨文档: 反封号 SOP 含设备指纹 + IP")
            else:
                result.add("warn", "RISK_ANTIBAN_FP",
                           "反封号 SOP 缺设备指纹或 IP 管理")
        return result


__all__ = ["RiskValidator", "RISK_DOC_REQUIREMENTS"]
