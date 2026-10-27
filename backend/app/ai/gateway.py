"""模型网关：业务代码只提任务类型与策略档位，模型细节全部隔离在外部配置。

移植自 gongkao-learning-os（FAST/BALANCED/STRONG 三档 + JSON schema 校验），裁剪了
视觉与回退分支，保持骨架最小。
"""
import json
import logging
from typing import Type, TypeVar

from pydantic import BaseModel

from .config import load_gateway_config
from .providers.base import ModelProvider
from .providers.mock import MockModelProvider
from .providers.openai_compatible import OpenAICompatibleProvider
from .schemas import (
    GatewayConfig, GenerationResult, Message, ModelPolicy,
    PolicyNotConfiguredError, ProviderUnavailableError, SchemaValidationError,
    TaskType, TruncatedGenerationError,
)

logger = logging.getLogger(__name__)
T = TypeVar('T', bound=BaseModel)


class ModelGateway:
    def __init__(self, config: GatewayConfig | None = None, custom_provider: ModelProvider | None = None):
        self.config = config or load_gateway_config()
        self._custom_provider = custom_provider
        self._providers: dict[str, ModelProvider] = {
            'mock': MockModelProvider(),
            'openai_compatible': OpenAICompatibleProvider(),
        }

    async def generate(self, task_type: TaskType | str, messages: list[Message],
                       schema: Type[T] | None = None,
                       model_policy: ModelPolicy | None = None) -> GenerationResult:
        policy: ModelPolicy = model_policy or self.config.task_policy_map.get(task_type, 'BALANCED')
        if policy not in self.config.policies:
            raise PolicyNotConfiguredError(f'策略 {policy} 未配置')
        policy_cfg = self.config.policies[policy]
        provider = self._custom_provider or self._providers.get(policy_cfg.provider, self._providers['mock'])

        processed = list(messages)
        if schema is not None:
            schema_str = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            fmt = f'You MUST reply with valid JSON conforming to this schema:\n{schema_str}'
            if processed and processed[0].role == 'system':
                processed[0] = Message(role='system', content=processed[0].content + '\n\n' + fmt)
            else:
                processed.insert(0, Message(role='system', content=fmt))

        try:
            raw_text, usage = await provider.generate(
                processed, policy_cfg, json_mode=schema is not None)
        except TruncatedGenerationError:
            budget = min(16384, policy_cfg.max_tokens * 2)
            if budget <= policy_cfg.max_tokens:
                raise
            raw_text, usage = await provider.generate(
                processed, policy_cfg.model_copy(update={'max_tokens': budget}),
                json_mode=schema is not None)
        except ProviderUnavailableError as exc:
            # 端点不可达或密钥失效时降级到离线 mock，保证学习流程不中断，
            # 同时把真实原因带回给调用方（degraded 标记）。
            logger.warning('模型不可用，降级到 mock：%s', exc)
            mock = self._providers['mock']
            raw_text, usage = await mock.generate(
                processed, policy_cfg.model_copy(update={'provider': 'mock', 'model': 'mock-degraded'}),
                json_mode=False)
            return GenerationResult(
                data=self._validate(raw_text, schema), raw_text=raw_text,
                policy_used=policy, model_name='mock-degraded', provider_name='mock',
                tokens_used=usage)

        return GenerationResult(
            data=self._validate(raw_text, schema), raw_text=raw_text,
            policy_used=policy, model_name=policy_cfg.model,
            provider_name=policy_cfg.provider, tokens_used=usage)

    @staticmethod
    def _validate(raw_text: str, schema):
        if schema is None:
            return raw_text
        cleaned = raw_text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            cleaned = '\n'.join(lines).strip()
        try:
            return schema.model_validate_json(cleaned)
        except Exception as exc:
            raise SchemaValidationError(f'{schema.__name__} 校验失败: {exc}\nRaw: {raw_text}') from exc


_default_gateway: ModelGateway | None = None


def get_model_gateway() -> ModelGateway:
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = ModelGateway()
    return _default_gateway


def set_model_gateway(gateway: ModelGateway | None) -> None:
    global _default_gateway
    _default_gateway = gateway
