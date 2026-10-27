"""AI 教师层：mock 网关全链路、人设注入、会话持久化。"""
import asyncio

from app.ai.gateway import ModelGateway
from app.ai.schemas import GatewayConfig, Message, ModelPolicyConfig
from app.ai.teacher import teacher_reply


def _mock_gateway() -> ModelGateway:
    from app.ai.providers.mock import MockModelProvider
    cfg = GatewayConfig(
        policies={
            'FAST': ModelPolicyConfig(provider='mock', model='fast-v1'),
            'BALANCED': ModelPolicyConfig(provider='mock', model='bal-v1'),
            'STRONG': ModelPolicyConfig(provider='mock', model='strong-v1'),
        },
        task_policy_map={'tutor_hint': 'FAST', 'tutor_explanation': 'BALANCED', 'chat': 'BALANCED'},
    )
    return ModelGateway(config=cfg, custom_provider=MockModelProvider())


def test_teacher_three_modes_and_persistence(installed_db):
    db = installed_db
    gw = _mock_gateway()
    r1 = asyncio.run(teacher_reply(db, 'demo-pack', 'hint', '不知道从哪里入手',
                                   question_id='q1', gateway=gw))
    assert r1['mock'] is True and r1['mode'] == 'hint'
    r2 = asyncio.run(teacher_reply(db, 'demo-pack', 'explain', '讲讲这题',
                                   question_id='q1', gateway=gw))
    assert r2['model'] == 'bal-v1'
    r3 = asyncio.run(teacher_reply(db, 'demo-pack', 'chat', '这个考点还有别的例子吗',
                                   question_id='q1', history=[{'role': 'user', 'content': '上一轮'}],
                                   gateway=gw))
    assert r3['reply']
    rows = db.execute('SELECT * FROM ai_conversations ORDER BY id').fetchall()
    assert len(rows) == 6   # 每轮 user+assistant
    assert {r['mode'] for r in rows} == {'hint', 'explain', 'chat'}


def test_teacher_hint_never_receives_answer(installed_db):
    """提示模式的系统提示词不得包含标准答案（内容层面由提示词约束）。"""
    from app.ai.teacher import build_messages
    pack = installed_db.execute('SELECT * FROM packs WHERE id=?', ('demo-pack',)).fetchone()
    question = {'type': 'single_choice', 'stem': 's', 'options': ['dynasty', 'x', 'y', 'z'],
                'answer': 'A', 'explanation': 'dynasty 是王朝'}
    msgs = build_messages(dict(pack), 'hint', question, [], '给点提示')
    system = msgs[0].content
    assert '标准答案' not in system and 'dynasty 是王朝' not in system
    msgs2 = build_messages(dict(pack), 'explain', question, [], '请讲解')
    assert '标准答案' in msgs2[0].content


def test_gateway_schema_validation():
    from pydantic import BaseModel

    class Reply(BaseModel):
        summary: str

    class FakeProvider:
        async def generate(self, messages, config, json_mode=False):
            text = '```json\n{"summary": "ok"}\n```'
            return text, 8

    cfg = GatewayConfig(
        policies={'BALANCED': ModelPolicyConfig(provider='fake', model='m')},
        task_policy_map={'chat': 'BALANCED'},
    )
    gw = ModelGateway(config=cfg, custom_provider=FakeProvider())
    result = asyncio.run(gw.generate('chat', [Message(role='user', content='hi')], schema=Reply))
    assert result.data.summary == 'ok'   # 自动剥离 ```json 围栏并校验
