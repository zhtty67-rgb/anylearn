"""确定性 Mock Provider：测试与离线演示用，不依赖任何外部服务。"""
from ..schemas import Message, ModelPolicyConfig
from .base import ModelProvider


class MockModelProvider(ModelProvider):
    async def generate(self, messages: list[Message], config: ModelPolicyConfig,
                       json_mode: bool = False) -> tuple[str, int | None]:
        system = next((m.content for m in messages if m.role == 'system'), '')
        user = next((m.content for m in reversed(messages) if m.role == 'user'), '')
        reply = (
            f'[mock:{config.model}] 已收到你的问题。{user[:80]}\n'
            f'教学建议（离线演示）：先回顾本考点定义，再对照题目关键词定位；'
            f'如需完整讲解请配置真实模型（model_config.toml）。'
        )
        if '不泄露' in system or '提示' in system:
            reply = f'[mock:{config.model}] 提示：从题干关键词入手，回想该考点的核心定义，排除明显不符的选项。'
        return reply, len(reply)
