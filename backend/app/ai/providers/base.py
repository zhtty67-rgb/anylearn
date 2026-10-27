"""Provider 抽象：网关只认这个接口，具体模型/端点/密钥全部外部配置。"""
from abc import ABC, abstractmethod

from ..schemas import Message, ModelPolicyConfig


class ModelProvider(ABC):
    @abstractmethod
    async def generate(self, messages: list[Message], config: ModelPolicyConfig,
                       json_mode: bool = False) -> tuple[str, int | None]:
        """返回 (原始文本, token用量)。"""
        raise NotImplementedError
