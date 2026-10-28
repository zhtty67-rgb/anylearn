"""确定性 Mock Provider：测试与离线演示用，不依赖任何外部服务。

注意：mock 在评审任务上永远不应被当成真实判断。评审器会识别 provider=='mock'
并把结论降级为 pending，这里只需保证输出结构合法即可。
"""
import json

from ..schemas import Message, ModelPolicyConfig
from .base import ModelProvider


class MockModelProvider(ModelProvider):
    async def generate(self, messages: list[Message], config: ModelPolicyConfig,
                       json_mode: bool = False) -> tuple[str, int | None]:
        system = next((m.content for m in messages if m.role == 'system'), '')
        user = next((m.content for m in reversed(messages) if m.role == 'user'), '')
        if json_mode or 'JSON' in system:
            # 评审任务：按 schema 回一个合法但明确标记为无法判断的结构
            payload = self._mock_review(user)
            reply = json.dumps(payload, ensure_ascii=False)
            return reply, len(reply)
        reply = (
            f'[mock:{config.model}] 已收到你的问题。{user[:80]}\n'
            f'教学建议（离线演示）：先回顾本考点定义，再对照题目关键词定位；'
            f'如需完整讲解请配置真实模型（model_config.toml）。'
        )
        if '不泄露' in system or '提示' in system:
            reply = f'[mock:{config.model}] 提示：从题干关键词入手，回想该考点的核心定义，排除明显不符的选项。'
        return reply, len(reply)

    @staticmethod
    def _mock_review(user: str) -> dict:
        items = []
        for line in user.splitlines():
            if line.startswith('- '):
                items.append({'item': line[2:].strip(), 'met': False,
                              'reason': '离线 mock 无法判断语义'})
        return {'verdict': 'unclear', 'items': items,
                'summary': '离线 mock 不做真实评审，请配置模型或人工评审。'}
