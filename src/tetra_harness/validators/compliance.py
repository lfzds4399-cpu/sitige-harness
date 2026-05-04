"""compliance — 平台合规扫描.

扫 content/marketing/kook/bot/partners 各模块, 命中红线词且不在豁免上下文 → finding.
- 抖音/小红书禁词: 27 项绝对化广告法词 + 16 项游戏陪玩红线词
- B 站宽松
- SKILL E5 上下文豁免: 含 "禁止/禁用/不准/避免" 等的行不报
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import Validator, ValidationResult, line_is_exempt, safe_read


# 27 项广告法绝对化词 (《广告法》第九条)
ABSOLUTE_AD_WORDS: tuple[str, ...] = (
    "国家级", "世界级", "最高级", "最佳", "最具", "最爱", "最赚", "最优",
    "顶级", "极品", "极致", "首选", "首发", "全网最", "史上最",
    "唯一", "独一无二", "100%", "百分百", "绝对", "永远",
    "第一品牌", "全国第一", "全球第一", "宇宙第一",
    "万能", "包治",
)

# 16 项游戏陪玩平台红线词
GAME_BANNED_WORDS: tuple[str, ...] = (
    "代练", "上分包过", "包上分", "撞车包赢", "卖号", "买号",
    "包赔", "封号包赔", "外挂", "破解", "辅助器", "秒升段",
    "赌博", "套利", "刷分", "工作室代打",
)

# 平台严格度
PLATFORM_RULES = {
    "douyin": {
        "banned": ABSOLUTE_AD_WORDS + GAME_BANNED_WORDS,
        "severity": "error",
    },
    "xiaohongshu": {
        "banned": ABSOLUTE_AD_WORDS + GAME_BANNED_WORDS,
        "severity": "error",
    },
    "wechat": {
        "banned": ABSOLUTE_AD_WORDS + GAME_BANNED_WORDS,
        "severity": "error",
    },
    "bilibili": {
        # B 站对游戏陪玩词宽松, 但广告法仍要遵守
        "banned": ABSOLUTE_AD_WORDS,
        "severity": "warn",
    },
}

# 平台 → 扫描路径 (相对 root)
PLATFORM_PATHS = {
    "douyin": ("content/douyin", "content/抖音", "marketing"),
    "xiaohongshu": ("content/xiaohongshu", "content/小红书", "marketing"),
    "bilibili": ("content/bilibili", "content/B站", "marketing"),
    "wechat": ("wechat", "marketing"),
    "all": ("kook", "bot", "partners", "qq-channels"),
}


def _scan_dir(root: Path, sub: str, words: tuple[str, ...],
              severity: str, platform: str) -> list[tuple]:
    """扫一个子目录下所有 .md / .py / .ts / .vue 文件, 命中红线词 → finding."""
    findings = []
    target = root / sub
    if not target.exists():
        return findings
    suffixes = (".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".html")

    files: list[Path] = []
    if target.is_file():
        files = [target]
    else:
        files = [p for p in target.rglob("*")
                 if p.is_file() and p.suffix.lower() in suffixes]

    for f in files:
        text = safe_read(f)
        if not text:
            continue
        # 跳过 平台关键词审核表 / 红线词列表 文件本身 (它就是要列举禁词的)
        rel = str(f.relative_to(root))
        if "关键词审核表" in rel or "黑名单" in rel or "封禁规则" in rel:
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            if line_is_exempt(line):
                continue
            for w in words:
                if w in line:
                    findings.append((
                        severity,
                        f"BANNED_WORD",
                        f"[{platform}] 红线词 '{w}' @ {rel}",
                        f, line_no,
                    ))
                    break  # 一行一报, 不重复
    return findings


class ComplianceValidator(Validator):
    name = "compliance"
    description = "抖音/小红书/B站/微信 平台禁词扫描 + 27 项广告法绝对化词"

    def run(self, project_root: Path, config: Optional[dict] = None) -> ValidationResult:
        result = ValidationResult(validator=self.name)
        with self._timed(result):
            total_files_scanned = 0
            for platform, paths in PLATFORM_PATHS.items():
                if platform == "all":
                    rule = {"banned": ABSOLUTE_AD_WORDS + GAME_BANNED_WORDS,
                            "severity": "warn"}
                else:
                    rule = PLATFORM_RULES.get(platform, {})
                if not rule:
                    continue
                for sub in paths:
                    p = project_root / sub
                    if p.exists() and p.is_dir():
                        total_files_scanned += sum(
                            1 for f in p.rglob("*") if f.is_file()
                        )
                    for sev, code, msg, fpath, ln in _scan_dir(
                        project_root, sub, rule["banned"],
                        rule["severity"], platform
                    ):
                        result.add(sev, code, msg, file=fpath, line=ln)

            result.add_ok(f"已扫描 {total_files_scanned} 个文件, 平台合规检查完成")
        return result


__all__ = [
    "ComplianceValidator",
    "ABSOLUTE_AD_WORDS", "GAME_BANNED_WORDS",
    "PLATFORM_RULES", "PLATFORM_PATHS",
]
