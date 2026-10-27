"""AI 网关的数据结构与任务类型。"""
from typing import Any, Literal, Optional

from pydantic import BaseModel

ModelPolicy = Literal['FAST', 'BALANCED', 'STRONG']
TaskType = Literal[
    'tutor_hint',       # 答前提示（不泄露答案）
    'tutor_explanation',  # 答后完整讲解
    'chat',             # 自由问答
    'grading',          # 主观题AI判分（预留）
    'question_generation',  # 变式题生成（预留）
]


class ModelPolicyConfig(BaseModel):
    provider: str = 'mock'
    model: str = 'mock-model'
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    supports_vision: bool = False


class Message(BaseModel):
    role: str
    content: str


class GenerationResult(BaseModel):
    data: Any
    raw_text: str
    policy_used: ModelPolicy
    model_name: str
    provider_name: str
    tokens_used: Optional[int] = None


class GatewayConfig(BaseModel):
    policies: dict[ModelPolicy, ModelPolicyConfig]
    task_policy_map: dict[str, ModelPolicy]


class PolicyNotConfiguredError(Exception):
    pass


class ProviderUnavailableError(Exception):
    pass


class SchemaValidationError(Exception):
    pass


class TruncatedGenerationError(Exception):
    pass
