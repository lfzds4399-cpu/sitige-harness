"""storage.secrets — sops + env 加密 secrets.

优先级链 (CompositeSecret): SopsSecret > EnvSecret > Default.

依赖 (运行期): sops 二进制 + age key 或 GPG key.
开发机没有 sops 时, 自动 fallback 到 EnvSecret.

任何 subprocess 调用走 utils.subprocess_safe.safe_run.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Union

try:
    import yaml  # pyproject 已声明 pyyaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from tetra_harness.utils.subprocess_safe import safe_run

_log = logging.getLogger("tetra.secrets")


class SecretProvider(Protocol):
    """统一 secret provider 协议."""

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]: ...


# ---------- env ----------
class EnvSecret:
    """从 os.environ 读 (含 .env, 假设上层已 dotenv.load_dotenv)."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        full = f"{self.prefix}{key}" if self.prefix else key
        return os.environ.get(full, default)


# ---------- sops ----------
class SopsSecret:
    """sops 加密文件读. 文件可以是 .yaml / .json / .env 格式 sops 加密.

    用法:
        s = SopsSecret(Path("configs/secrets.enc.yaml"))
        s.get("OPENAI_API_KEY")
    """

    def __init__(
        self,
        encrypted_file: Union[str, Path],
        *,
        timeout: int = 30,
    ) -> None:
        self.path = Path(encrypted_file)
        self.timeout = timeout
        self._cache: Optional[Dict[str, Any]] = None

    def _ensure_decrypted(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            _log.warning("SopsSecret: 文件不存在 %s", self.path)
            self._cache = {}
            return self._cache

        r = safe_run(["sops", "-d", str(self.path)], timeout=self.timeout)
        if r.returncode != 0:
            _log.warning(
                "SopsSecret: sops -d 失败 rc=%s, fallback 空 dict\n%s",
                r.returncode,
                (r.stderr or "")[-400:],
            )
            self._cache = {}
            return self._cache

        text = r.stdout or ""
        suffix = self.path.suffix.lower()
        try:
            if suffix in (".yaml", ".yml"):
                if yaml is None:
                    raise RuntimeError("pyyaml 未安装")
                data = yaml.safe_load(text) or {}
            elif suffix == ".json":
                data = json.loads(text)
            else:
                # 当 .env 风格 KEY=VALUE
                data = {}
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            _log.error("SopsSecret: 解析失败 %s", e)
            data = {}

        if not isinstance(data, dict):
            _log.warning("SopsSecret: 顶层不是 dict, 忽略")
            data = {}
        self._cache = data
        return self._cache

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        d = self._ensure_decrypted()
        # 支持 a.b.c 路径
        cur: Any = d
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        if cur is None:
            return default
        return str(cur)

    def reload(self) -> None:
        self._cache = None


# ---------- composite ----------
class CompositeSecret:
    """多 provider 串联, 第一个返回非 None 即取."""

    def __init__(self, providers: list) -> None:
        self.providers = providers

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        for p in self.providers:
            try:
                v = p.get(key, None)
            except Exception as e:  # pragma: no cover
                _log.warning("provider %s 取 %s 失败: %s", p, key, e)
                continue
            if v is not None and v != "":
                return v
        return default


# ---------- factory ----------
_singleton: Optional[SecretProvider] = None


def _build_from_env() -> SecretProvider:
    provider = os.getenv("SECRETS_PROVIDER", "env").strip().lower()
    if provider == "env":
        return EnvSecret()
    if provider == "sops":
        path = os.getenv("SOPS_FILE", "configs/secrets.enc.yaml")
        return SopsSecret(path)
    if provider == "composite":
        path = os.getenv("SOPS_FILE", "configs/secrets.enc.yaml")
        return CompositeSecret([SopsSecret(path), EnvSecret()])
    _log.warning("SECRETS_PROVIDER=%s 不识别, fallback env", provider)
    return EnvSecret()


def get_secrets() -> SecretProvider:
    global _singleton
    if _singleton is None:
        _singleton = _build_from_env()
    return _singleton


def reset_secrets() -> None:
    """测试用."""
    global _singleton
    _singleton = None


__all__ = [
    "SecretProvider",
    "EnvSecret",
    "SopsSecret",
    "CompositeSecret",
    "get_secrets",
    "reset_secrets",
]
