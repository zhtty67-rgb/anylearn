"""AI 教师在教学步骤中的两种动作：苏格拉底追问、费曼讲解评审。

设计约束（与 lesson 层一致）：
- 教师可以**生成追问**、**指出漏洞**、**追问到底**，但**不能写等级**。
- 费曼评审输出的是「哪几条没讲清 + 为什么」，不是分数。等级由 lesson 层按证据推导。
- 预置误解（concepts.misconceptions_json）是追问的首选靶子。
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from ..ai.schemas import Message
from .gateway import ModelGateway, get_model_gateway

SOCRATIC_SYSTEM = (
    '你是苏格拉底式的教师。规则：\n'
    '1. 绝不直接给出答案或结论，只通过提问引导学生自己发现；\n'
    '2. 每次只问一个最关键的追问，不要连抛多个问题；\n'
    '3. 如果学生答得含糊，追问具体例子或反例；\n'
    '4. 如果学生表述里出现目标误解，优先针对那个误解设问；\n'
    '5. 语气平实，不夸奖也不打击，只推动思考。'
)

FEYNMAN_SYSTEM = (
    '你在评估学习者「讲给初学者听」的讲解。规则：\n'
    '1. 只看是否讲清，不看文笔与篇幅；\n'
    '2. 每条 rubric 逐条判断，理由必须引用学习者原文；\n'
    '3. 出现术语堆砌、只背定义没有例子、无法说清局限，都算没讲清；\n'
    '4. 不给分数，只给「哪条没讲清 + 一句话怎么补」。'
)


class Probe(BaseModel):
    question: str = Field(description='一个最关键的追问，一句话')
    targets: str = Field(description='这一问想击中的薄弱点或误解，便于教师记录')
    why: str = Field(description='为什么现在问这个')


class RubricItem(BaseModel):
    item: str
    met: bool
    reason: str


class FeynmanReview(BaseModel):
    verdict: Literal['pass', 'fail', 'unclear']
    items: list[RubricItem]
    gaps: list[str] = Field(description='没讲清的点，每条一句话，指出怎么补')


def _concept_block(concept, misconceptions: list[str]) -> str:
    lines = [f'概念：{concept["name"]}',
             f'要点：{concept["summary"] or "（未提供）"}']
    if misconceptions:
        lines.append('学生常见误解：')
        lines.extend(f'- {m}' for m in misconceptions)
    return '\n'.join(lines)


async def socratic_probe(*, concept, misconceptions: list[str], utterance: str,
                         history: list[dict] | None = None,
                         gateway: ModelGateway | None = None) -> dict:
    """根据学习者刚说的话，生成一个最关键的追问。"""
    gw = gateway or get_model_gateway()
    convo = '\n'.join(f'{h["role"]}：{h["content"]}' for h in (history or [])[-6:])
    user = (f'{_concept_block(concept, misconceptions)}\n\n'
            f'本轮学习者的话：{utterance or "（还没有说话）"}\n'
            f'此前对话：\n{convo or "（无）"}\n\n'
            f'请给出一个最关键的追问。')
    result = await gw.generate('socratic_probe',
                               [Message(role='system', content=SOCRATIC_SYSTEM),
                                Message(role='user', content=user)],
                               schema=Probe)
    probe: Probe = result.data
    degraded = result.provider_name == 'mock'
    return {'question': probe.question, 'targets': probe.targets, 'why': probe.why,
            'model': result.model_name, 'provider': result.provider_name,
            'degraded': degraded}


async def feynman_review(*, concept, rubric: list[str], explanation: str,
                         gateway: ModelGateway | None = None) -> dict:
    """评审费曼式讲解。返回逐条结果与缺口，不给等级。"""
    gw = gateway or get_model_gateway()
    items = '\n'.join(f'- {r}' for r in rubric) or '- 能向初学者讲清核心含义'
    user = (f'{_concept_block(concept, [])}\n\n'
            f'评审标准：\n{items}\n\n'
            f'学习者的讲解：\n"""\n{explanation}\n"""\n\n'
            f'请逐条判断并指出没讲清的地方。')
    result = await gw.generate('feynman_review',
                               [Message(role='system', content=FEYNMAN_SYSTEM),
                                Message(role='user', content=user)],
                               schema=FeynmanReview)
    review: FeynmanReview = result.data
    degraded = result.provider_name == 'mock'
    met = sum(1 for i in review.items if i.met)
    verdict = review.verdict
    if degraded:
        verdict = 'unclear'   # mock 不参与判定
    return {'verdict': verdict, 'items': [i.model_dump() for i in review.items],
            'gaps': review.gaps, 'met': met, 'total': len(review.items),
            'model': result.model_name, 'provider': result.provider_name,
            'degraded': degraded}


def concept_context(db, concept_id: str) -> tuple[dict, list[str]]:
    """取概念及其预置误解，供两个教师动作共用。"""
    row = db.execute('SELECT * FROM concepts WHERE id=?', (concept_id,)).fetchone()
    if row is None:
        raise KeyError(f'概念不存在: {concept_id}')
    concept = {'id': row['id'], 'name': row['name'], 'summary': row['summary'] or ''}
    try:
        misconceptions = json.loads(row['misconceptions_json'] or '[]')
    except json.JSONDecodeError:
        misconceptions = []
    return concept, misconceptions
