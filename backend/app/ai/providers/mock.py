"""确定性 Mock Provider：测试与离线演示用，不依赖任何外部服务。

注意：mock 在评审任务上永远不应被当成真实判断。评审器会识别 provider=='mock'
并把结论降级为 pending / unclear，这里只需保证**输出结构与请求的 schema 一致**，
否则调用方的 schema 校验会直接把学习流程打挂（这是踩过的坑）。
"""
import json
import re

from ..schemas import Message, ModelPolicyConfig
from .base import ModelProvider


class MockModelProvider(ModelProvider):
    async def generate(self, messages: list[Message], config: ModelPolicyConfig,
                       json_mode: bool = False) -> tuple[str, int | None]:
        system = next((m.content for m in messages if m.role == 'system'), '')
        user = next((m.content for m in reversed(messages) if m.role == 'user'), '')
        if json_mode or 'JSON' in system:
            payload = self._structured(system, user, messages)
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

    def _structured(self, system: str, user: str, messages: list[Message]) -> dict:
        """按网关注入的 JSON schema 文本来决定返回形状，而不是靠中文关键词猜。

        注入文本形如：
          You MUST reply with valid JSON conforming to this schema:
          { ...json schema..., "$defs": {"RubricItem": {...}} }
        schema 里可能嵌套 $defs，所以必须按 JSON 解析，不能用正则捞第一个 required。
        """
        joined = '\n'.join(m.content for m in messages)
        schema = self._extract_schema(joined)
        props = (schema or {}).get('properties', {})
        required = (schema or {}).get('required', [])
        items_schema = self._items_schema(props.get('items'), schema)
        items = self._rubric_items(user, items_schema)

        base = {}
        if 'question' in required or 'question' in props:
            base.update({'question': '你能举一个具体例子说明这一点吗？',
                         'targets': '离线 mock 无法定位薄弱点',
                         'why': '离线 mock 只做占位，配置真实模型后会针对你的表述追问'})
        if 'verdict' in required or 'verdict' in props:
            base['verdict'] = 'unclear'
        if 'items' in required or 'items' in props:
            base['items'] = items
        if 'summary' in required or 'summary' in props:
            base['summary'] = '离线 mock 不做真实评审，请配置模型或人工评审。'
        if 'gaps' in required or 'gaps' in props:
            base['gaps'] = ['离线 mock 无法判断哪一条没讲清']
        if 'score' in required or 'score' in props:
            base['score'] = 0
        # schema 要求了但上面没覆盖的字段统一补空，保证校验通过
        for field in required:
            base.setdefault(field, '')
        return base

    @staticmethod
    def _extract_schema(text: str) -> dict | None:
        marker = 'conforming to this schema:'
        idx = text.find(marker)
        if idx < 0:
            return None
        raw = text[idx + len(marker):].strip()
        depth, start = 0, None
        for i, ch in enumerate(raw):
            if ch == '{':
                if start is None:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    @staticmethod
    def _items_schema(items_prop, root: dict) -> dict:
        """拿到数组元素的字段定义。

        pydantic 的数组属性形如：
          "items": {"type": "array", "items": {"$ref": "#/$defs/RubricItem"}}
        元素 schema 藏在 items_prop['items'] 里，不是 items_prop 本身。
        """
        if not isinstance(items_prop, dict):
            return {}
        elem = items_prop.get('items', items_prop)
        if not isinstance(elem, dict):
            return {}
        ref = elem.get('$ref')
        defs = root.get('$defs') or root.get('definitions') or {}
        if not ref:
            return elem
        name = ref.split('/')[-1]
        if name in defs:
            return defs[name]
        found = MockModelProvider._items_schema(elem, root)
        return found if found.get('properties') else {}

    @staticmethod
    def _rubric_items(user: str, item_schema: dict) -> list[dict]:
        fields = set((item_schema or {}).get('properties', {}))
        items = []
        for line in user.splitlines():
            if not line.startswith('- '):
                continue
            item = {'item': line[2:].strip()}
            if 'met' in fields:
                item['met'] = False
            if 'reason' in fields:
                item['reason'] = '离线 mock 无法判断语义'
            items.append(item)
        return items
