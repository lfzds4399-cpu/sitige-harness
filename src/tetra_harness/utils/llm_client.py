"""llm_client — 国产 LLM 5 平台统一接入 (OpenAI 兼容协议).

支持: deepseek (默认) / zhipu / qwen / kimi / doubao
统一 .chat() 接口 + retry + cost_tracker.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional

from tetra_harness.config import get_env
from tetra_harness.utils.cost_tracker import CostTracker
from tetra_harness.utils.retry import retry_with_backoff

Provider = Literal["deepseek", "zhipu", "qwen", "kimi", "doubao"]

_log = logging.getLogger("tetra.llm")


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    default_model: str
    api_key_env: str
    base_url_env: str
    model_env: str
    # 粗略 (USD / 1k tokens) — 仅供 cost_tracker 估算; 真实价请按官方
    in_per_1k: float = 0.0
    out_per_1k: float = 0.0


PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        base_url_env="DEEPSEEK_BASE_URL",
        model_env="DEEPSEEK_MODEL",
        in_per_1k=0.00014,
        out_per_1k=0.00028,
    ),
    "zhipu": ProviderSpec(
        name="zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
        api_key_env="ZHIPU_API_KEY",
        base_url_env="ZHIPU_BASE_URL",
        model_env="ZHIPU_MODEL",
        in_per_1k=0.0007,
        out_per_1k=0.0007,
    ),
    "qwen": ProviderSpec(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        api_key_env="QWEN_API_KEY",
        base_url_env="QWEN_BASE_URL",
        model_env="QWEN_MODEL",
        in_per_1k=0.0006,
        out_per_1k=0.0017,
    ),
    "kimi": ProviderSpec(
        name="kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-32k",
        api_key_env="KIMI_API_KEY",
        base_url_env="KIMI_BASE_URL",
        model_env="KIMI_MODEL",
        in_per_1k=0.0033,
        out_per_1k=0.0033,
    ),
    "doubao": ProviderSpec(
        name="doubao",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-pro-32k",
        api_key_env="DOUBAO_API_KEY",
        base_url_env="DOUBAO_BASE_URL",
        model_env="DOUBAO_MODEL",
        in_per_1k=0.0011,
        out_per_1k=0.0028,
    ),
}


class LLMClient:
    """国产 LLM 统一 client.

    用法:
        client = LLMClient.from_env()         # 读 LLM_DEFAULT_PROVIDER
        client = LLMClient("deepseek")        # 显式指定
        text = await client.chat([{"role":"user","content":"..."}])
    """

    def __init__(
        self,
        provider: Provider = "deepseek",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if provider not in PROVIDERS:
            raise ValueError(
                f"unsupported provider {provider!r}, choose from {list(PROVIDERS)}"
            )
        spec = PROVIDERS[provider]
        self.provider: Provider = provider
        self.spec = spec
        self.api_key = api_key or get_env(spec.api_key_env)
        self.base_url = base_url or get_env(spec.base_url_env) or spec.base_url
        self.model = model or get_env(spec.model_env) or spec.default_model
        self._client: Any = None  # lazy AsyncOpenAI

    @classmethod
    def from_env(cls) -> "LLMClient":
        provider = (get_env("LLM_DEFAULT_PROVIDER", "deepseek") or "deepseek").lower()
        if provider not in PROVIDERS:
            _log.warning("LLM_DEFAULT_PROVIDER=%s 不在白名单, 回退 deepseek", provider)
            provider = "deepseek"
        return cls(provider)  # type: ignore[arg-type]

    # ---------- internals ----------
    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai 包未安装, pip install openai>=1.40"
            ) from e
        if not self.api_key:
            raise RuntimeError(
                f"{self.spec.api_key_env} 未配置 (.env 或环境变量)"
            )
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def _estimate_cost(self, in_tokens: int, out_tokens: int) -> float:
        return (
            in_tokens / 1000.0 * self.spec.in_per_1k
            + out_tokens / 1000.0 * self.spec.out_per_1k
        )

    # ---------- 公共 API ----------
    @retry_with_backoff(max=3, exp=2)
    async def chat(
        self,
        messages: Iterable[dict[str, Any]],
        model: Optional[str] = None,
        **kw: Any,
    ) -> str:
        """OpenAI 兼容 chat.completions, 返回首条 choice 的 content."""
        client = self._get_client()
        use_model = model or self.model
        msgs = list(messages)

        resp = await client.chat.completions.create(
            model=use_model,
            messages=msgs,
            **kw,
        )

        try:
            content = resp.choices[0].message.content or ""
        except (IndexError, AttributeError):
            content = ""

        # cost 估算
        usage = getattr(resp, "usage", None)
        in_t = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_t = getattr(usage, "completion_tokens", 0) if usage else 0
        cost = self._estimate_cost(in_t, out_t)
        CostTracker.track(
            provider=self.provider,
            model=use_model,
            input_tokens=in_t,
            output_tokens=out_t,
            usd=cost,
        )
        return content

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"LLMClient(provider={self.provider!r}, "
            f"base_url={self.base_url!r}, model={self.model!r})"
        )
