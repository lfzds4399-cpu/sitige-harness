"""alerter — 告警通道 (钉钉 / 飞书 / 阿里云邮件 / 腾讯企业邮 SMTP).

国产合规, 不引 PagerDuty / Opsgenie.

环境变量约定 (configs/observability.yaml 引用 env name):
    DINGDING_WEBHOOK / DINGDING_SECRET   钉钉机器人 webhook + 加签
    FEISHU_WEBHOOK / FEISHU_SECRET       飞书机器人 webhook + 加签 (可选)
    ALIYUN_MAIL_HOST / ALIYUN_MAIL_USER  / ALIYUN_MAIL_PASS  阿里云邮件推送 SMTP
    TENCENT_MAIL_HOST / ...              腾讯企业邮 SMTP

阈值规则示例 (在调用方按业务判定):
    pipeline 失败             → error  钉钉
    LLM 成本超阈值            → warn   飞书
    validator 累计 error >50  → critical 钉钉@all
    订单堆积                  → warn   钉钉

使用:
    from tetra_harness.observability.alerter import (
        DingdingAlerter, FeishuAlerter, EmailAlerter, CompositeAlerter, Level
    )

    alerter = CompositeAlerter([
        DingdingAlerter(webhook=os.getenv("DINGDING_WEBHOOK")),
        FeishuAlerter(webhook=os.getenv("FEISHU_WEBHOOK")),
    ])
    await alerter.send("error", "Pipeline failed", "content_pipeline @ stage=script")
"""
from __future__ import annotations

import asyncio
import base64
import email.mime.text
import hashlib
import hmac
import logging
import os
import smtplib
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

_log = logging.getLogger("tetra.alerter")

# httpx 已是项目依赖, 不需 try
try:
    import httpx  # type: ignore[import-not-found]
    HAS_HTTPX = True
except ImportError:  # pragma: no cover
    HAS_HTTPX = False
    httpx = None  # type: ignore[assignment]

Level = Literal["info", "warn", "error", "critical"]

_LEVEL_EMOJI = {
    "info": "ℹ️",
    "warn": "⚠️",
    "error": "❌",
    "critical": "🚨",
}


# ============================================================
# 接口
# ============================================================
class Alerter(ABC):
    """告警通道抽象接口."""

    name: str = "base"

    @abstractmethod
    async def send(self, level: Level, title: str, body: str) -> bool:
        """发送告警. 返回是否成功."""

    async def close(self) -> None:
        """收尾 (HTTP client 关闭等)."""


# ============================================================
# 钉钉
# ============================================================
class DingdingAlerter(Alerter):
    """钉钉机器人 webhook + 加签算法.

    申请: 群设置 → 智能群助手 → 添加机器人 → 自定义 → 安全设置勾"加签".
    """

    name = "dingding"

    def __init__(
        self,
        webhook: str | None = None,
        secret: str | None = None,
        at_all_on_critical: bool = True,
        timeout: float = 5.0,
    ):
        self.webhook = webhook or os.getenv("DINGDING_WEBHOOK", "")
        self.secret = secret or os.getenv("DINGDING_SECRET", "")
        self.at_all_on_critical = at_all_on_critical
        self.timeout = timeout

    def _sign(self) -> tuple[str, str]:
        """钉钉加签: 时间戳 + secret HMAC-SHA256 base64 url-encode."""
        ts = str(round(time.time() * 1000))
        if not self.secret:
            return ts, ""
        string_to_sign = f"{ts}\n{self.secret}"
        h = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(h))
        return ts, sign

    def _build_url(self) -> str:
        if not self.secret:
            return self.webhook
        ts, sign = self._sign()
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={ts}&sign={sign}"

    def _payload(self, level: Level, title: str, body: str) -> dict:
        emoji = _LEVEL_EMOJI[level]
        at = {"isAtAll": level == "critical" and self.at_all_on_critical}
        return {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{emoji} [{level.upper()}] {title}"[:60],
                "text": (
                    f"### {emoji} [{level.upper()}] {title}\n\n"
                    f"{body}\n\n"
                    f"> 来源: tetra-harness · {time.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
            },
            "at": at,
        }

    async def send(self, level: Level, title: str, body: str) -> bool:
        if not self.webhook:
            _log.warning("[dingding] webhook 未配置, 跳过")
            return False
        if not HAS_HTTPX:
            _log.error("[dingding] httpx 缺失")
            return False
        url = self._build_url()
        payload = self._payload(level, title, body)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as cli:
                r = await cli.post(url, json=payload)
                if r.status_code == 200 and r.json().get("errcode") == 0:
                    _log.info("[dingding] sent: %s", title)
                    return True
                _log.error("[dingding] failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            _log.error("[dingding] error: %s", e)
        return False


# ============================================================
# 飞书
# ============================================================
class FeishuAlerter(Alerter):
    """飞书自定义机器人 webhook (post 卡片)."""

    name = "feishu"

    def __init__(
        self,
        webhook: str | None = None,
        secret: str | None = None,
        timeout: float = 5.0,
    ):
        self.webhook = webhook or os.getenv("FEISHU_WEBHOOK", "")
        self.secret = secret or os.getenv("FEISHU_SECRET", "")
        self.timeout = timeout

    def _sign(self, ts: int) -> str:
        """飞书加签: timestamp + key 做 HMAC-SHA256."""
        if not self.secret:
            return ""
        string_to_sign = f"{ts}\n{self.secret}"
        h = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(h).decode("utf-8")

    def _payload(self, level: Level, title: str, body: str) -> dict:
        emoji = _LEVEL_EMOJI[level]
        ts = int(time.time())
        payload: dict[str, Any] = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{emoji} [{level.upper()}] {title}",
                    },
                    "template": {
                        "info": "blue", "warn": "yellow",
                        "error": "red", "critical": "red",
                    }[level],
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": body}},
                    {"tag": "note", "elements": [
                        {"tag": "plain_text",
                         "content": f"tetra-harness · {time.strftime('%Y-%m-%d %H:%M:%S')}"}
                    ]},
                ],
            },
        }
        if self.secret:
            payload["timestamp"] = str(ts)
            payload["sign"] = self._sign(ts)
        return payload

    async def send(self, level: Level, title: str, body: str) -> bool:
        if not self.webhook:
            _log.warning("[feishu] webhook 未配置, 跳过")
            return False
        if not HAS_HTTPX:
            _log.error("[feishu] httpx 缺失")
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as cli:
                r = await cli.post(self.webhook, json=self._payload(level, title, body))
                data = r.json() if r.status_code == 200 else {}
                if r.status_code == 200 and data.get("StatusCode", data.get("code", -1)) in (0, None):
                    _log.info("[feishu] sent: %s", title)
                    return True
                _log.error("[feishu] failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            _log.error("[feishu] error: %s", e)
        return False


# ============================================================
# 邮件 (阿里云邮件推送 / 腾讯企业邮 SMTP)
# ============================================================
@dataclass
class SMTPConfig:
    host: str
    port: int = 465
    user: str = ""
    password: str = ""
    use_ssl: bool = True
    sender: str = ""  # 发件地址 (邮件推送通常 = user)


class EmailAlerter(Alerter):
    """SMTP 邮件告警. 阿里云邮件推送 / 腾讯企业邮通用.

    阿里云邮件推送默认:
        host=smtpdm.aliyun.com  port=465  ssl=True
    腾讯企业邮:
        host=smtp.exmail.qq.com  port=465  ssl=True
    """

    name = "email"

    def __init__(
        self,
        smtp: SMTPConfig | None = None,
        to: Iterable[str] | str = (),
        env_prefix: str = "ALIYUN_MAIL_",
    ):
        if smtp is None:
            smtp = SMTPConfig(
                host=os.getenv(f"{env_prefix}HOST", "smtpdm.aliyun.com"),
                port=int(os.getenv(f"{env_prefix}PORT", "465")),
                user=os.getenv(f"{env_prefix}USER", ""),
                password=os.getenv(f"{env_prefix}PASS", ""),
                use_ssl=os.getenv(f"{env_prefix}SSL", "true").lower() != "false",
                sender=os.getenv(f"{env_prefix}SENDER", "")
                or os.getenv(f"{env_prefix}USER", ""),
            )
        self.smtp = smtp
        self.to = [to] if isinstance(to, str) else list(to)

    def _build_msg(self, level: Level, title: str, body: str) -> email.mime.text.MIMEText:
        emoji = _LEVEL_EMOJI[level]
        full_body = (
            f"{emoji} [{level.upper()}] {title}\n\n"
            f"{body}\n\n"
            f"---\ntetra-harness · {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        msg = email.mime.text.MIMEText(full_body, "plain", "utf-8")
        msg["Subject"] = f"{emoji} [tetra/{level}] {title}"
        msg["From"] = self.smtp.sender or self.smtp.user
        msg["To"] = ", ".join(self.to)
        return msg

    def _send_blocking(self, msg: email.mime.text.MIMEText) -> bool:
        try:
            if self.smtp.use_ssl:
                cli = smtplib.SMTP_SSL(self.smtp.host, self.smtp.port, timeout=10)
            else:
                cli = smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=10)
            with cli:
                if self.smtp.user:
                    cli.login(self.smtp.user, self.smtp.password)
                cli.sendmail(msg["From"], self.to, msg.as_string())
            return True
        except Exception as e:  # noqa: BLE001
            _log.error("[email] smtp error: %s", e)
            return False

    async def send(self, level: Level, title: str, body: str) -> bool:
        if not self.to or not self.smtp.host:
            _log.warning("[email] 收件人/SMTP 未配置, 跳过")
            return False
        msg = self._build_msg(level, title, body)
        ok = await asyncio.to_thread(self._send_blocking, msg)
        if ok:
            _log.info("[email] sent: %s -> %s", title, self.to)
        return ok


# ============================================================
# 多通道复合 alerter
# ============================================================
@dataclass
class CompositeAlerter(Alerter):
    """同时打多个通道. 任一成功即视为发送成功."""

    name: str = "composite"
    channels: list[Alerter] = field(default_factory=list)

    async def send(self, level: Level, title: str, body: str) -> bool:
        if not self.channels:
            _log.warning("[composite] 无可用通道")
            return False
        results = await asyncio.gather(
            *(ch.send(level, title, body) for ch in self.channels),
            return_exceptions=True,
        )
        ok_any = False
        for ch, r in zip(self.channels, results):
            if isinstance(r, Exception):
                _log.error("[%s] exc: %s", ch.name, r)
            elif r:
                ok_any = True
        return ok_any

    async def close(self) -> None:
        for ch in self.channels:
            try:
                await ch.close()
            except Exception:  # noqa: BLE001
                pass


# ============================================================
# 阈值判定 helper (调用方用)
# ============================================================
@dataclass
class AlertThresholds:
    llm_cost_usd_per_hour: float = 5.0
    pipeline_failure_rate: float = 0.1
    validator_errors_per_run: int = 50
    order_backlog: int = 100


def evaluate_thresholds(
    th: AlertThresholds,
    *,
    llm_cost_last_hour: float = 0.0,
    pipeline_fail_rate: float = 0.0,
    validator_errors: int = 0,
    order_backlog: int = 0,
) -> list[tuple[Level, str, str]]:
    """根据阈值跑一遍, 返回 [(level, title, body), ...] 待发送告警列表."""
    out: list[tuple[Level, str, str]] = []
    if llm_cost_last_hour > th.llm_cost_usd_per_hour:
        out.append(("warn", "LLM 成本超阈值",
                    f"过去 1h LLM 成本 ${llm_cost_last_hour:.2f} > 阈值 ${th.llm_cost_usd_per_hour:.2f}"))
    if pipeline_fail_rate > th.pipeline_failure_rate:
        out.append(("error", "Pipeline 失败率过高",
                    f"近期失败率 {pipeline_fail_rate:.1%} > 阈值 {th.pipeline_failure_rate:.1%}"))
    if validator_errors > th.validator_errors_per_run:
        out.append(("critical", "Validator 累计错误超限",
                    f"单次跑 validator error={validator_errors} > {th.validator_errors_per_run}"))
    if order_backlog > th.order_backlog:
        out.append(("warn", "订单堆积",
                    f"未派单订单 {order_backlog} > 阈值 {th.order_backlog}"))
    return out


__all__ = [
    "Level",
    "Alerter",
    "DingdingAlerter",
    "FeishuAlerter",
    "EmailAlerter",
    "SMTPConfig",
    "CompositeAlerter",
    "AlertThresholds",
    "evaluate_thresholds",
]
