"""OpenAI 兼容 Provider：任何 /v1/chat/completions 端点均可接入。"""
import json

import httpx

from ..schemas import Message, ModelPolicyConfig, ProviderUnavailableError, TruncatedGenerationError
from .base import ModelProvider


class OpenAICompatibleProvider(ModelProvider):
    async def generate(self, messages: list[Message], config: ModelPolicyConfig,
                       json_mode: bool = False) -> tuple[str, int | None]:
        if not config.base_url or not config.api_key:
            raise ProviderUnavailableError('未配置 base_url/api_key（model_config.toml 或 AI_BASE_URL/AI_API_KEY）')
        payload: dict = {
            'model': config.model,
            'messages': [m.model_dump() for m in messages],
            'temperature': config.temperature,
            'max_tokens': config.max_tokens,
        }
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
        headers = {'Authorization': f'Bearer {config.api_key}'}
        try:
            client = httpx.AsyncClient(timeout=config.timeout_seconds)
        except ImportError:
            # 系统配了 SOCKS 代理但未装 socksio：模型端点通常直连，降级为忽略系统代理
            client = httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False)
        try:
            async with client:
                resp = await client.post(f'{config.base_url.rstrip("/")}/chat/completions',
                                         json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f'模型端点不可达: {exc}') from exc
        if resp.status_code != 200:
            raise ProviderUnavailableError(f'模型端点返回 {resp.status_code}: {resp.text[:200]}')
        data = resp.json()
        choice = (data.get('choices') or [{}])[0]
        finish = choice.get('finish_reason')
        text = (choice.get('message') or {}).get('content') or ''
        if finish == 'length' or not text.strip():
            raise TruncatedGenerationError(f'模型输出被截断或为空 (finish_reason={finish})')
        usage = (data.get('usage') or {}).get('total_tokens')
        return text, usage
