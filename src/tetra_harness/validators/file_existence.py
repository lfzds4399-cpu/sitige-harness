"""file_existence — 145+ 项业务文件/目录/内容存在性检查.

完整迁移自 harness/audit.py (18.3KB). 按 18+ 模块拆函数:
brand / web / miniprogram / app / wechat / bot / server / partners / seller /
content / marketing / legal / risk / ops / biz / kook / qq-channels / deploy /
compliance / meta

每 check_<module> 返回 list[Finding-like] 元组, run() 汇总成 ValidationResult.
保持"上下文豁免" SKILL E5: 含禁止/禁用/不准/避免 的行不被红线词命中.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from .base import Validator, ValidationResult, line_is_exempt, safe_read


# ----------------- helpers (仿 audit.py 风格, 但 root 显式传) -----------------
def _file_exists(root: Path, p: str) -> bool:
    return (root / p).is_file()


def _dir_exists(root: Path, p: str) -> bool:
    return (root / p).is_dir()


def _file_size(root: Path, p: str) -> int:
    f = root / p
    return f.stat().st_size if f.exists() else 0


def _read_text(root: Path, p: str) -> str:
    return safe_read(root / p)


def _list_files(root: Path, d: str, suffix: str = ".md") -> list[str]:
    p = root / d
    if not p.is_dir():
        return []
    return [f.name for f in p.iterdir() if f.is_file() and f.suffix == suffix]


# ============================================================================
# 18 个模块 check 函数 — 每个返回 (ok_count, [(severity, code, msg, detail)...])
# ============================================================================

def _module_simple_dir(root: Path, name: str, dir_name: str | None = None) -> tuple[int, list]:
    """简单目录存在性检查 (brand/web/miniprogram/app/wechat/bot/server/partners/seller/content/marketing)."""
    d = dir_name or name
    if _dir_exists(root, d):
        n = sum(1 for _ in (root / d).rglob("*") if _.is_file())
        return 1, [("ok", f"DIR_EXISTS_{d.upper()}", f"{d}/ 目录存在 ({n} 文件)", "")] if name == "brand" else (1, [("ok", f"DIR_EXISTS_{d.upper()}", f"{d}/ 目录存在", "")])[1] and (1, [("ok", f"DIR_EXISTS", f"{d}/ 目录存在", "")])[1]
    return 0, [("info", "DIR_MISSING", f"{d}/ 目录不存在", "")]


# 上面那种写法可读性差, 重写每个模块单独函数 ↓


def check_brand(root: Path) -> list[tuple]:
    out = []
    if _dir_exists(root, "brand"):
        n = sum(1 for _ in (root / "brand").rglob("*") if _.is_file())
        out.append(("ok", "BRAND_DIR", f"brand/ 目录存在 ({n} 文件)", ""))
    else:
        out.append(("info", "BRAND_MISSING", "brand/ 目录不存在（独立创建中）", ""))
    return out


def _simple_dir(root: Path, name: str) -> list[tuple]:
    if _dir_exists(root, name):
        return [("ok", f"{name.upper()}_DIR", f"{name}/ 目录存在", "")]
    return [("info", f"{name.upper()}_MISSING", f"{name}/ 目录待开发", "")]


def check_web(root): return _simple_dir(root, "web")
def check_miniprogram(root): return _simple_dir(root, "miniprogram")
def check_app(root): return _simple_dir(root, "app")
def check_wechat(root): return _simple_dir(root, "wechat")
def check_bot(root): return _simple_dir(root, "bot")
def check_server(root): return _simple_dir(root, "server")
def check_partners(root): return _simple_dir(root, "partners")
def check_seller(root): return _simple_dir(root, "seller")
def check_content(root): return _simple_dir(root, "content")
def check_marketing(root): return _simple_dir(root, "marketing")


def check_legal(root: Path) -> list[tuple]:
    out = []
    required = [
        "用户服务条款.md", "隐私政策.md", "合作工作室协议.md",
        "师傅签约协议.md", "实名认证须知.md", "未成年人保护承诺.md",
        "资金安全告知.md", "退款仲裁规则.md", "知识产权声明.md",
        "免责声明.md", "legal-checklist.md",
    ]
    for f in required:
        path = f"legal/{f}"
        if _file_exists(root, path):
            sz = _file_size(root, path)
            if sz < 1500:
                out.append(("warn", "LEGAL_TOO_SMALL", f"{f} 偏小 ({sz}B < 1500)", path))
            else:
                out.append(("ok", "LEGAL_OK", f"{f} ({sz//1024}KB)", path))
        else:
            out.append(("error", "LEGAL_MISSING", f"{f} 缺失", path))
    n = len(_list_files(root, "legal"))
    if n < 11:
        out.append(("warn", "LEGAL_COUNT_LOW", f"legal/ 仅 {n} 篇 (<11)", ""))
    else:
        out.append(("ok", "LEGAL_COUNT_OK", f"legal/ {n} 篇齐全", ""))
    return out


def check_risk(root: Path) -> list[tuple]:
    out = []
    required = [
        "实名审核 SOP.md", "未成年识别 SOP.md", "反封号 SOP.md",
        "资金安全 SOP.md", "投诉仲裁 SOP.md", "危机公关 SOP.md",
        "黑名单管理.md", "合作工作室风控.md", "平台关键词审核表.md",
        "数据安全 SOP.md", "应急预案.md",
    ]
    for f in required:
        path = f"risk/{f}"
        if _file_exists(root, path):
            sz = _file_size(root, path)
            out.append(("ok", "RISK_OK", f"{f} ({sz//1024}KB)", path))
        else:
            out.append(("error", "RISK_MISSING", f"{f} 缺失", path))
    n = len(_list_files(root, "risk"))
    if n < 11:
        out.append(("warn", "RISK_COUNT_LOW", f"risk/ 仅 {n} 篇 (<11)", ""))
    else:
        out.append(("ok", "RISK_COUNT_OK", f"risk/ {n} 篇齐全", ""))
    return out


def check_ops(root: Path) -> list[tuple]:
    out = []
    required = [
        "接单 SOP.md", "派单 SOP.md", "客服话术库.md",
        "投诉处理 SOP.md", "退款 SOP.md", "撞车队战术 SOP.md",
        "师傅管理 SOP.md", "内容审核 SOP.md", "数据回收 SOP.md",
        "KPI 看板.md", "周会 SOP.md", "招商 SOP.md",
    ]
    for f in required:
        path = f"ops/{f}"
        if _file_exists(root, path):
            sz = _file_size(root, path)
            out.append(("ok", "OPS_OK", f"{f} ({sz//1024}KB)", path))
        else:
            out.append(("error", "OPS_MISSING", f"{f} 缺失", path))
    mermaid_count = sum(1 for f in required
                        if "```mermaid" in _read_text(root, f"ops/{f}"))
    if mermaid_count >= 3:
        out.append(("ok", "OPS_MERMAID", f"{mermaid_count} 个 SOP 含 Mermaid 流程图", ""))
    else:
        out.append(("warn", "OPS_MERMAID_LOW", f"仅 {mermaid_count} 个 SOP 含 Mermaid", ""))
    return out


def check_biz(root: Path) -> list[tuple]:
    out = []
    required = [
        "90 天 Sprint.md", "12 月 P&L.md", "单位经济模型.md",
        "GTM 策略.md", "竞品分析.md", "创始人 Day-7.md",
        "融资策略.md", "退出策略.md", "风险登记册.md", "招聘计划.md",
    ]
    for f in required:
        path = f"biz/{f}"
        if _file_exists(root, path):
            sz = _file_size(root, path)
            out.append(("ok", "BIZ_OK", f"{f} ({sz//1024}KB)", path))
        else:
            out.append(("error", "BIZ_MISSING", f"{f} 缺失", path))

    pl = _read_text(root, "biz/12 月 P&L.md")
    months = sum(1 for k in ["M1", "M3", "M6", "M12"] if k in pl)
    if months >= 4:
        out.append(("ok", "BIZ_PL_MONTHS", "12 月 P&L 覆盖 M1/M3/M6/M12", ""))
    else:
        out.append(("warn", "BIZ_PL_MONTHS_LOW", f"P&L 月度覆盖不全 ({months}/4)", ""))

    sprint = _read_text(root, "biz/90 天 Sprint.md")
    weeks = sum(1 for w in [f"Week {i}" for i in range(1, 13)] if w in sprint)
    if weeks >= 8:
        out.append(("ok", "BIZ_SPRINT_WEEKS", f"90 天 Sprint 含 {weeks} 周里程碑", ""))
    else:
        out.append(("warn", "BIZ_SPRINT_WEEKS_LOW", f"90 天 Sprint 仅 {weeks} 周", ""))

    day7 = _read_text(root, "biz/创始人 Day-7.md")
    tasks = day7.count("- [ ]")
    if tasks >= 48:
        out.append(("ok", "BIZ_DAY7_TASKS", f"Day-7 含 {tasks} 任务 (≥48)", ""))
    else:
        out.append(("warn", "BIZ_DAY7_TASKS_LOW", f"Day-7 仅 {tasks} 任务", ""))
    return out


def check_compliance_redlines(root: Path) -> list[tuple]:
    """5 大法务红线 (实名/未保/工作室独立/退款 7 场景/敏感词表)."""
    out = []
    # 红线 1: 实名认证三件套
    auth_files = ["legal/实名认证须知.md", "risk/实名审核 SOP.md", "risk/未成年识别 SOP.md"]
    auth_hit = sum(1 for p in auth_files if _file_exists(root, p))
    if auth_hit == 3:
        out.append(("ok", "REDLINE_1_KYC", "🔴 红线 1: 实名认证 三件套齐全", ""))
    else:
        out.append(("error", "REDLINE_1_KYC", f"红线 1: 实名认证 仅 {auth_hit}/3", "; ".join(auth_files)))

    # 红线 2: 未保
    minor = _read_text(root, "legal/未成年人保护承诺.md") + _read_text(root, "risk/未成年识别 SOP.md")
    keywords = ["18 周岁", "实名", "人脸", "健康系统", "监护人"]
    hits = sum(1 for k in keywords if k in minor)
    if hits >= 4:
        out.append(("ok", "REDLINE_2_MINOR", f"🔴 红线 2: 未成年保护 关键词 {hits}/{len(keywords)}", ""))
    else:
        out.append(("error", "REDLINE_2_MINOR", f"红线 2: 未成年保护 关键词不足 ({hits}/{len(keywords)})", ""))

    # 红线 3: 工作室独立承担
    workshop = _read_text(root, "legal/合作工作室协议.md")
    independent_keys = ["独立承担", "独立法人", "信息撮合", "代收款项"]
    hits3 = sum(1 for k in independent_keys if k in workshop)
    if hits3 >= 3:
        out.append(("ok", "REDLINE_3_WORKSHOP",
                    f"🔴 红线 3: 工作室协议-独立承担 关键词 {hits3}/{len(independent_keys)}", ""))
    else:
        out.append(("error", "REDLINE_3_WORKSHOP",
                    f"红线 3: 独立承担条款不全 ({hits3}/{len(independent_keys)})", ""))

    # 红线 4: 退款 7 场景
    refund = _read_text(root, "legal/退款仲裁规则.md")
    scenes = sum(1 for k in [f"场景 {i}" for i in range(1, 8)] if k in refund)
    if scenes >= 7:
        out.append(("ok", "REDLINE_4_REFUND", "🔴 红线 4: 退款 7 场景齐全", ""))
    else:
        out.append(("error", "REDLINE_4_REFUND", f"红线 4: 退款仅 {scenes}/7 场景", ""))

    # 红线 5: 敏感词表
    keywords_tbl = _read_text(root, "risk/平台关键词审核表.md")
    platforms = ["抖音", "小红书", "B 站", "微信", "百度"]
    plat_hits = sum(1 for p in platforms if p in keywords_tbl)
    redlines = ["代练", "卖号", "外挂", "封号包赔"]
    rl_hits = sum(1 for r in redlines if r in keywords_tbl)
    if plat_hits == 5 and rl_hits == 4:
        out.append(("ok", "REDLINE_5_KW", "🔴 红线 5: 敏感词表覆盖 5 平台 + 4 红线词", ""))
    else:
        out.append(("warn", "REDLINE_5_KW", f"红线 5: 平台 {plat_hits}/5, 红线词 {rl_hits}/4", ""))
    return out


def check_kook(root: Path) -> list[tuple]:
    out = []
    docs = [
        "kook/README.md", "kook/server-structure.md", "kook/roles.md",
        "kook/welcome-flow.md", "kook/auto-mod.md", "kook/data-callback.md",
        "kook/三栈整合.md",
    ]
    for f in docs:
        if _file_exists(root, f):
            sz = _file_size(root, f)
            if sz < 800:
                out.append(("warn", "KOOK_DOC_SMALL", f"{f} 偏小 ({sz}B)", f))
            else:
                out.append(("ok", "KOOK_DOC_OK", f"{f} ({sz//1024}KB)", ""))
        else:
            out.append(("error", "KOOK_DOC_MISSING", f"{f} 缺失", f))

    bot_files = [
        "kook/bot/main.py", "kook/bot/config.py", "kook/bot/requirements.txt",
        "kook/bot/.env.example", "kook/bot/Dockerfile", "kook/bot/docker-compose.yml",
        "kook/bot/README.md",
        "kook/bot/handlers/__init__.py", "kook/bot/handlers/welcome.py",
        "kook/bot/handlers/order.py", "kook/bot/handlers/match.py",
        "kook/bot/handlers/cs.py", "kook/bot/handlers/admin.py",
        "kook/bot/handlers/voice.py",
        "kook/bot/services/server_api.py", "kook/bot/services/rag.py",
    ]
    bot_hit = sum(1 for p in bot_files if _file_exists(root, p))
    if bot_hit == len(bot_files):
        out.append(("ok", "KOOK_BOT_SKEL", f"kook/bot/ 代码骨架 {bot_hit}/{len(bot_files)} 全齐", ""))
    else:
        out.append(("error", "KOOK_BOT_SKEL", f"kook/bot/ 仅 {bot_hit}/{len(bot_files)} 文件", ""))

    bad_imports = ["import discord", "from discord", "from slack_sdk",
                   "import openai", "from openai", "import telegram"]
    main_text = (_read_text(root, "kook/bot/main.py")
                 + _read_text(root, "kook/bot/services/rag.py")
                 + _read_text(root, "kook/bot/services/server_api.py"))
    bad_hit = next((b for b in bad_imports if b in main_text), None)
    if bad_hit:
        out.append(("error", "KOOK_OVERSEAS_SDK", f"违反海外 SDK 红线: 含 '{bad_hit}'", ""))
    else:
        out.append(("ok", "KOOK_NO_OVERSEAS_SDK",
                    "无海外 SDK 引用（discord/slack/openai/telegram）", ""))

    roles_text = _read_text(root, "kook/roles.md")
    if "#FFD700" in roles_text and "#0A0A0B" in roles_text:
        out.append(("ok", "KOOK_BRAND_COLOR", "黑金配色锁定（#FFD700 / #0A0A0B）", ""))
    else:
        out.append(("warn", "KOOK_BRAND_COLOR", "未在 roles.md 显式声明黑金 hex", ""))

    bad_color_lines = []
    for line in roles_text.splitlines():
        if "#A2185F" in line or "#9D00FF" in line:
            if not line_is_exempt(line, ("TetraGG", "海外版")):
                bad_color_lines.append(line.strip()[:60])
    if bad_color_lines:
        out.append(("error", "KOOK_BAD_COLOR",
                    "出现 TetraGG 红紫色（违反配色锁）", "; ".join(bad_color_lines)))
    else:
        out.append(("ok", "KOOK_COLOR_LOCK", "无非法红紫色（黑金锁通过）", ""))

    welcome_text = _read_text(root, "kook/welcome-flow.md")
    if "信息撮合" in welcome_text and ("18" in welcome_text or "未成年" in welcome_text):
        out.append(("ok", "KOOK_WELCOME_COMPLY", "welcome-flow 合规声明齐全（信息撮合 + 未成年拦截）", ""))
    else:
        out.append(("error", "KOOK_WELCOME_COMPLY", "welcome-flow 缺少合规声明", ""))

    forbidden_in_facing = ["代练服务", "包过", "封号包赔", "100% 赔付", "卖号", "外挂"]
    facing_files = [
        "kook/welcome-flow.md", "kook/bot/handlers/welcome.py", "kook/bot/handlers/order.py",
    ]
    all_violations = []
    for f in facing_files:
        text = _read_text(root, f)
        for line in text.splitlines():
            if line_is_exempt(line):
                continue
            for w in forbidden_in_facing:
                if w in line:
                    all_violations.append(f"{w} @ {line.strip()[:50]}")
                    break
    if all_violations:
        out.append(("error", "KOOK_FACING_BANNED",
                    f"用户话术含红线词 ({len(all_violations)} 处)",
                    all_violations[0] if all_violations else ""))
    else:
        out.append(("ok", "KOOK_FACING_CLEAN", "用户话术无红线词", ""))
    return out


def check_qq_channels(root: Path) -> list[tuple]:
    out = []
    docs = [
        "qq-channels/README.md", "qq-channels/structure.md",
        "qq-channels/bot.md", "qq-channels/cross-post.md",
    ]
    for f in docs:
        if _file_exists(root, f):
            sz = _file_size(root, f)
            if sz < 600:
                out.append(("warn", "QQ_DOC_SMALL", f"{f} 偏小 ({sz}B)", f))
            else:
                out.append(("ok", "QQ_DOC_OK", f"{f} ({sz//1024}KB)", ""))
        else:
            out.append(("error", "QQ_DOC_MISSING", f"{f} 缺失", f))

    bot_text = _read_text(root, "qq-channels/bot.md")
    if "botpy" in bot_text:
        out.append(("ok", "QQ_BOTPY", "bot.md 使用 botpy 官方 SDK", ""))
    else:
        out.append(("error", "QQ_NO_BOTPY", "bot.md 未引用 botpy", ""))
    cmd_count = bot_text.count("async def _cmd_")
    if cmd_count >= 5:
        out.append(("ok", "QQ_CMD_COUNT", f"bot.md 含 {cmd_count} 个命令骨架（≥5）", ""))
    else:
        out.append(("warn", "QQ_CMD_LOW", f"bot.md 仅 {cmd_count} 个命令骨架", ""))

    if any(b in bot_text for b in ["discord.py", "slack_sdk", "telegram.ext"]):
        out.append(("error", "QQ_OVERSEAS_SDK", "bot.md 含海外 SDK 引用", ""))
    else:
        out.append(("ok", "QQ_NO_OVERSEAS_SDK", "bot.md 无海外 SDK 引用", ""))

    readme = _read_text(root, "qq-channels/README.md")
    if "QQ 频道" in readme and "KOOK" in readme and ("微信" in readme or "wechat" in readme.lower()):
        out.append(("ok", "QQ_TRISTACK", "README 含三栈分工说明", ""))
    else:
        out.append(("warn", "QQ_TRISTACK_PARTIAL", "README 三栈分工不完整", ""))
    return out


def check_deploy(root: Path) -> list[tuple]:  # noqa: C901
    out = []

    # 1. docker-compose.yml
    if _file_exists(root, "docker-compose.yml"):
        text = _read_text(root, "docker-compose.yml")
        sz = _file_size(root, "docker-compose.yml")
        out.append(("ok", "DEPLOY_COMPOSE", f"docker-compose.yml ({sz//1024}KB)", ""))
        services = ["web:", "server:", "bot:", "kook-bot:", "postgres:", "redis:", "nginx:"]
        hits = sum(1 for s in services if s in text)
        if hits >= 7:
            out.append(("ok", "DEPLOY_SERVICES",
                        "7 服务齐全 (web/server/bot/kook-bot/postgres/redis/nginx)", ""))
        else:
            out.append(("error", "DEPLOY_SERVICES_MISSING", f"服务不全 ({hits}/7)", ""))
        if "healthcheck:" in text and text.count("healthcheck:") >= 4:
            out.append(("ok", "DEPLOY_HC", f"healthcheck 已配置 ({text.count('healthcheck:')} 个)", ""))
        else:
            out.append(("warn", "DEPLOY_HC_LOW", "healthcheck 不足 (<4)", ""))
        if "service_healthy" in text:
            out.append(("ok", "DEPLOY_DEPENDS", "depends_on condition: service_healthy 已用", ""))
        else:
            out.append(("warn", "DEPLOY_DEPENDS_LOW", "depends_on 未用 service_healthy", ""))
        if text.count("restart: unless-stopped") >= 6:
            out.append(("ok", "DEPLOY_RESTART",
                        f"restart: unless-stopped ({text.count('restart: unless-stopped')} 处)", ""))
        else:
            out.append(("warn", "DEPLOY_RESTART_LOW", "restart 策略不全", ""))
        if "pg_data" in text and "redis_data" in text and "uploads" in text:
            out.append(("ok", "DEPLOY_VOLS", "持久化卷齐 (pg/redis/uploads)", ""))
        else:
            out.append(("error", "DEPLOY_VOLS_MISSING", "持久化卷缺", ""))
        if "tetra-net" in text or "networks:" in text:
            out.append(("ok", "DEPLOY_NET", "内部网络已配", ""))
        else:
            out.append(("warn", "DEPLOY_NET_MISSING", "未声明 networks", ""))
        if "postgres:16-alpine" in text:
            out.append(("ok", "DEPLOY_PG", "postgres:16-alpine", ""))
        else:
            out.append(("warn", "DEPLOY_PG_VER", "postgres 镜像不是 16-alpine", ""))
    else:
        out.append(("error", "DEPLOY_COMPOSE_MISSING", "docker-compose.yml 缺失", ""))

    # 2. .env.全栈.example
    if _file_exists(root, ".env.全栈.example"):
        env_text = _read_text(root, ".env.全栈.example")
        required = ["POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET",
                    "WECHAT_APP_ID", "QQ_APP_ID", "KOOK_BOT_TOKEN",
                    "DEEPSEEK_API_KEY", "ICP_BEIAN", "BACKUP_PROVIDER"]
        miss = [k for k in required if k not in env_text]
        if not miss:
            out.append(("ok", "DEPLOY_ENV", f".env.全栈.example 关键字齐 ({len(required)} 个)", ""))
        else:
            out.append(("error", "DEPLOY_ENV_MISSING", f".env 缺关键字: {','.join(miss)}", ""))
        forbidden = ["AWS_", "AZURE_", "GCP_", "CLOUDFLARE_TOKEN", "VERCEL_TOKEN",
                     "HEROKU_", "DIGITALOCEAN_"]
        bad = [k for k in forbidden if k in env_text]
        if bad:
            out.append(("error", "DEPLOY_OVERSEAS_KEY", f".env 含海外服务 KEY: {','.join(bad)}", ""))
        else:
            out.append(("ok", "DEPLOY_NO_OVERSEAS_KEY", "无海外服务 KEY", ""))
    else:
        out.append(("error", "DEPLOY_ENV_FILE", ".env.全栈.example 缺失", ""))

    # 3. nginx
    nginx_files = ["ops/deploy/nginx.conf", "ops/deploy/conf.d/tetragg.conf"]
    for f in nginx_files:
        if _file_exists(root, f):
            out.append(("ok", "DEPLOY_NGINX_FILE", f"{f} ({_file_size(root, f)//1024}KB)", ""))
        else:
            out.append(("error", "DEPLOY_NGINX_MISSING", f"{f} 缺失", ""))

    nginx_text = _read_text(root, "ops/deploy/conf.d/tetragg.conf")
    if "return 301 https" in nginx_text:
        out.append(("ok", "DEPLOY_HTTPS_REDIR", "80 → 443 强制跳转", ""))
    else:
        out.append(("error", "DEPLOY_HTTPS_REDIR_MISSING", "无 80 → 443 强制", ""))
    if "limit_req" in nginx_text:
        out.append(("ok", "DEPLOY_RATELIMIT", "rate limit 已配", ""))
    else:
        out.append(("warn", "DEPLOY_RATELIMIT_MISSING", "无 rate limit", ""))
    if "ICP_BEIAN" in nginx_text or "icp" in nginx_text.lower():
        out.append(("ok", "DEPLOY_ICP", "备案号位置预留", ""))
    else:
        out.append(("warn", "DEPLOY_ICP_MISSING", "无备案号位置", ""))

    # 4. deploy.sh
    if _file_exists(root, "deploy.sh"):
        sh_text = _read_text(root, "deploy.sh")
        sz = _file_size(root, "deploy.sh")
        lines = sh_text.count("\n")
        out.append(("ok", "DEPLOY_SH", f"deploy.sh ({sz//1024}KB, {lines} 行)", ""))
        steps = sum(1 for i in range(1, 10) if f"{i}/9" in sh_text)
        if steps >= 9:
            out.append(("ok", "DEPLOY_SH_STEPS", "deploy.sh 9 步齐全", ""))
        else:
            out.append(("warn", "DEPLOY_SH_STEPS_LOW", f"deploy.sh 仅 {steps}/9 步", ""))
        if "seq 1 30" in sh_text or "for i in 1..30" in sh_text:
            out.append(("ok", "DEPLOY_HC_RETRY", "健康检查 30 次重试", ""))
        else:
            out.append(("warn", "DEPLOY_HC_RETRY_LOW", "健康检查重试次数 < 30", ""))
        if "set -e" in sh_text or "set -euo" in sh_text:
            out.append(("ok", "DEPLOY_SET_E", "set -e/-eu/-euo 启用", ""))
        else:
            out.append(("warn", "DEPLOY_SET_E_MISSING", "未启 set -e", ""))
        if any(k in sh_text for k in ["tsinghua", "npmmirror", "daocloud", "registry-mirrors"]):
            out.append(("ok", "DEPLOY_CN_MIRROR", "国产镜像源提示", ""))
        else:
            out.append(("warn", "DEPLOY_CN_MIRROR_MISSING", "未提国产镜像", ""))
    else:
        out.append(("error", "DEPLOY_SH_MISSING", "deploy.sh 缺失", ""))

    # 5. backup
    backup_files = ["ops/deploy/backup.sh", "ops/deploy/restore.sh"]
    for f in backup_files:
        if _file_exists(root, f):
            out.append(("ok", "DEPLOY_BACKUP_FILE", f"{f} ({_file_size(root, f)//1024}KB)", ""))
        else:
            out.append(("error", "DEPLOY_BACKUP_MISSING", f"{f} 缺失", ""))
    backup_text = _read_text(root, "ops/deploy/backup.sh")
    if "pg_dump" in backup_text and "BGSAVE" in backup_text:
        out.append(("ok", "DEPLOY_BACKUP_PGREDIS", "备份含 pg_dump + redis BGSAVE", ""))
    else:
        out.append(("error", "DEPLOY_BACKUP_INCOMPLETE", "备份不全", ""))
    providers = ["aliyun_oss", "tencent_cos", "qiniu"]
    p_hits = sum(1 for p in providers if p in backup_text)
    if p_hits == 3:
        out.append(("ok", "DEPLOY_BACKUP_OSS", "备份支持 3 家国产对象存储", ""))
    else:
        out.append(("warn", "DEPLOY_BACKUP_OSS_LOW", f"备份仅支持 {p_hits}/3 国产存储", ""))
    if "AWS" in backup_text or "s3://" in backup_text.lower():
        out.append(("error", "DEPLOY_BACKUP_OVERSEAS",
                    "备份含海外存储 (AWS/S3) — 红线违反", ""))
    else:
        out.append(("ok", "DEPLOY_BACKUP_NO_OVERSEAS", "备份无海外存储引用", ""))

    # 6. monitoring
    if _file_exists(root, "ops/deploy/monitoring.md"):
        mon = _read_text(root, "ops/deploy/monitoring.md")
        out.append(("ok", "DEPLOY_MON",
                    f"monitoring.md ({_file_size(root, 'ops/deploy/monitoring.md')//1024}KB)", ""))
        keys = ["阿里云 ARMS", "SLS", "钉钉", "Grafana", "cAdvisor", "GlitchTip", "监控宝"]
        hits = sum(1 for k in keys if k in mon)
        if hits >= 6:
            out.append(("ok", "DEPLOY_MON_KEYS", f"监控覆盖 {hits}/{len(keys)} (含国产)", ""))
        else:
            out.append(("warn", "DEPLOY_MON_KEYS_LOW", f"监控关键字 {hits}/{len(keys)}", ""))
    else:
        out.append(("error", "DEPLOY_MON_MISSING", "monitoring.md 缺失", ""))

    # 7. security
    if _file_exists(root, "ops/deploy/security-baseline.md"):
        sec = _read_text(root, "ops/deploy/security-baseline.md")
        out.append(("ok", "DEPLOY_SEC",
                    f"security-baseline.md ({_file_size(root, 'ops/deploy/security-baseline.md')//1024}KB)", ""))
        keys = ["ufw", "fail2ban", "certbot", "sops", "WAF", "logrotate", "等保"]
        hits = sum(1 for k in keys if k in sec)
        if hits >= 6:
            out.append(("ok", "DEPLOY_SEC_KEYS", f"安全基线覆盖 {hits}/{len(keys)}", ""))
        else:
            out.append(("warn", "DEPLOY_SEC_KEYS_LOW", f"安全基线 {hits}/{len(keys)}", ""))
    else:
        out.append(("error", "DEPLOY_SEC_MISSING", "security-baseline.md 缺失", ""))

    # 8. CI
    if _file_exists(root, "ops/deploy/coding-cicd.yml") and _file_exists(root, ".coding-ci/main.yml"):
        ci = _read_text(root, "ops/deploy/coding-cicd.yml")
        out.append(("ok", "DEPLOY_CI", "coding-cicd.yml + .coding-ci/main.yml 齐", ""))
        stages = ["lint", "test", "build", "deploy", "notify"]
        hits = sum(1 for s in stages if s in ci)
        if hits == 5:
            out.append(("ok", "DEPLOY_CI_STAGES", "CI 5 阶段齐 (lint/test/build/deploy/notify)", ""))
        else:
            out.append(("warn", "DEPLOY_CI_STAGES_LOW", f"CI 仅 {hits}/5 阶段", ""))
        if "uses: actions/" in ci:
            out.append(("error", "DEPLOY_CI_OVERSEAS", "CI 含 GitHub Actions (海外) — 红线违反", ""))
        else:
            out.append(("ok", "DEPLOY_CI_NO_OVERSEAS", "无 GitHub Actions 引用", ""))
    else:
        out.append(("error", "DEPLOY_CI_MISSING", "Coding CI 配置缺失", ""))

    # 9. RUNBOOK + 环境
    extra = ["ops/deploy/环境.md", "ops/deploy/RUNBOOK.md", "ops/deploy/letsencrypt.md"]
    for f in extra:
        if _file_exists(root, f):
            out.append(("ok", "DEPLOY_EXTRA_OK", f"{f} ({_file_size(root, f)//1024}KB)", ""))
        else:
            out.append(("error", "DEPLOY_EXTRA_MISSING", f"{f} 缺失", ""))

    runbook = _read_text(root, "ops/deploy/RUNBOOK.md")
    runbook_secs = ["服务宕了", "升级", "回滚", "慢查询", "凭据轮转", "值班", "联系方式"]
    hits = sum(1 for s in runbook_secs if s in runbook)
    if hits >= 6:
        out.append(("ok", "DEPLOY_RUNBOOK", f"RUNBOOK 7 大场景 {hits}/{len(runbook_secs)}", ""))
    else:
        out.append(("warn", "DEPLOY_RUNBOOK_LOW", f"RUNBOOK 场景 {hits}/{len(runbook_secs)}", ""))

    # 10. web Dockerfile
    if _file_exists(root, "web/Dockerfile"):
        out.append(("ok", "DEPLOY_WEB_DOCKERFILE", "web/Dockerfile 已补", ""))
    else:
        out.append(("error", "DEPLOY_WEB_DOCKERFILE_MISSING", "web/Dockerfile 缺", ""))

    # 11. 海外服务红线 (汇总扫描)
    all_deploy_text = "\n".join([
        _read_text(root, "docker-compose.yml"),
        _read_text(root, ".env.全栈.example"),
        _read_text(root, "ops/deploy/nginx.conf"),
        _read_text(root, "ops/deploy/conf.d/tetragg.conf"),
        _read_text(root, "ops/deploy/backup.sh"),
        _read_text(root, "ops/deploy/coding-cicd.yml"),
    ])
    bad = []
    for forbidden in ["aws s3 ", "amazonaws.com", "azure.com", "googleapis.com",
                      "vercel.app/deploy", "heroku.com", "netlify.com", "digitalocean.com"]:
        if forbidden in all_deploy_text.lower():
            bad.append(forbidden)
    if bad:
        out.append(("error", "DEPLOY_OVERSEAS", f"海外服务红线违反: {','.join(bad)}", ""))
    else:
        out.append(("ok", "DEPLOY_NO_OVERSEAS",
                    "无海外服务红线 (AWS/Azure/GCP/Vercel/Heroku/Netlify/DO)", ""))
    return out


def check_meta(root: Path) -> list[tuple]:
    out = []
    expected = ["brand", "web", "miniprogram", "app", "wechat", "bot", "server",
                "partners", "seller", "legal", "risk", "ops", "biz", "harness",
                "kook", "qq-channels"]
    for d in expected:
        if _dir_exists(root, d):
            n = sum(1 for _ in (root / d).rglob("*") if _.is_file())
            out.append(("ok", "META_DIR_OK", f"{d}/ ({n} 文件)", ""))
        else:
            out.append(("info", "META_DIR_MISSING", f"{d}/ 目录不存在", ""))

    counts = {
        "legal": len(_list_files(root, "legal")),
        "risk": len(_list_files(root, "risk")),
        "ops": len(_list_files(root, "ops")),
        "biz": len(_list_files(root, "biz")),
    }
    for name, n in counts.items():
        if n >= 10:
            out.append(("ok", "META_COUNT_OK", f"{name}/ {n} 篇", ""))
        else:
            out.append(("warn", "META_COUNT_LOW", f"{name}/ {n} 篇 (<10)", ""))
    return out


# ============================================================================
# Validator class
# ============================================================================

# (module_name, check_fn) — 顺序与 audit.py 一致, 保持 145✓
ALL_CHECKS: list[tuple[str, callable]] = [
    ("brand", check_brand),
    ("web", check_web),
    ("miniprogram", check_miniprogram),
    ("app", check_app),
    ("wechat", check_wechat),
    ("bot", check_bot),
    ("server", check_server),
    ("partners", check_partners),
    ("seller", check_seller),
    ("content", check_content),
    ("marketing", check_marketing),
    ("legal", check_legal),
    ("risk", check_risk),
    ("ops", check_ops),
    ("biz", check_biz),
    ("kook", check_kook),
    ("qq-channels", check_qq_channels),
    ("deploy", check_deploy),
    ("compliance", check_compliance_redlines),
    ("meta", check_meta),
]


class FileExistenceValidator(Validator):
    """145+ 项业务文件/内容存在性检查 (兼容旧 audit.py)."""

    name = "file_existence"
    description = "18 模块结构 + 145+ 项目文件存在性 + 内容关键字检查"

    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            for mod_name, fn in ALL_CHECKS:
                try:
                    items = fn(project_root)
                except Exception as e:  # 单模块挂掉不能影响其他
                    result.add("error", "MODULE_CRASH", f"{mod_name} 模块检查异常: {e}")
                    continue
                for item in items:
                    sev, code, msg, detail = item
                    if sev == "ok":
                        result.add_ok(msg)
                    else:
                        result.add(sev, code, msg, detail=detail)
        return result

    # 暴露每模块结果给 audit.py 薄壳, 用于保持旧版分模块输出
    def run_per_module(self, project_root: Path) -> list[tuple[str, list[tuple], float]]:
        results = []
        for mod_name, fn in ALL_CHECKS:
            t0 = time.perf_counter()
            try:
                items = fn(project_root)
            except Exception as e:
                items = [("error", "MODULE_CRASH", f"{mod_name} 检查异常: {e}", "")]
            elapsed = (time.perf_counter() - t0) * 1000
            results.append((mod_name, items, elapsed))
        return results


__all__ = [
    "FileExistenceValidator", "ALL_CHECKS",
    "check_brand", "check_web", "check_miniprogram", "check_app", "check_wechat",
    "check_bot", "check_server", "check_partners", "check_seller", "check_content",
    "check_marketing", "check_legal", "check_risk", "check_ops", "check_biz",
    "check_kook", "check_qq_channels", "check_deploy",
    "check_compliance_redlines", "check_meta",
]
