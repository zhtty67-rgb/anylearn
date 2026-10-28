"""AI 教师评审器：按 rubric 评审解释类产物，产出结构化判定。

三条不能退让的规则：
1. **模型必须逐条给 rubric 判定 + 理由**，不允许只给一个总分。
2. **判定是结构化的**（JSON schema 校验），不是自然语言里捞结论。
3. **模型不可用时降级为 mock，且 mock 永远判 pending**——宁可让人来评，
   也不能让一个离线占位符把「会用」判成「不会」或反过来。
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from ..ai.schemas import Message, SchemaValidationError
from .gateway import ModelGateway, get_model_gateway

PASS_RATIO = 0.5


class RubricItemVerdict(BaseModel):
    item: str = Field(description='rubric 里的原始条目文本')
    met: bool = Field(description='学习者解释是否满足这一条')
    reason: str = Field(description='判断依据，引用解释里的具体内容')


class ExplainReview(BaseModel):
    verdict: Literal['pass', 'fail', 'unclear'] = Field(
        description='pass=达到要求；fail=明显不满足；unclear=信息不足无法判断')
    items: list[RubricItemVerdict] = Field(description='逐条 rubric 判定，必须覆盖全部条目')
    summary: str = Field(description='一段话总结反馈，指出最该改的地方')


REVIEW_SYSTEM = (
    '你是一位严格的学科教师，正在评审学习者对某个概念的解释。\n'
    '要求：\n'
    '1. 对每一条 rubric 逐条判断，给出 met 与具体理由，理由必须引用学习者原文中的内容；\n'
    '2. 不许因为文笔好、篇幅长就给分，只看内容是否真的满足该条；\n'
    '3. 解释里没有证据支持的条目必须判 met=false，不要替学习者脑补；\n'
    '4. 全部条目都满足才可给 pass；大部分不满足给 fail；信息不足以判断给 unclear。'
)


def _build_messages(*, concept_name: str, concept_summary: str, rubric: list[str],
                    text: str) -> list[Message]:
    items = '\n'.join(f'- {r}' for r in rubric)
    user = (
        f'学生要解释的概念：{concept_name}\n'
        f'概念要点：{concept_summary or "（内容包未提供）"}\n\n'
        f'评审标准（逐条判定）：\n{items}\n\n'
        f'学生的解释原文：\n"""\n{text}\n"""\n\n'
        f'请按给定 JSON 结构输出判定，items 必须正好 {len(rubric)} 条，顺序与评审标准一致。'
    )
    return [Message(role='system', content=REVIEW_SYSTEM),
            Message(role='user', content=user)]


def _decide(review: ExplainReview, rubric: list[str]) -> tuple[str, float]:
    """把逐条判定折算成最终结论。覆盖率不足或模型自相矛盾时降为 unclear。"""
    if not rubric:
        return 'unclear', 0.0
    if len(review.items) != len(rubric):
        return 'unclear', 0.0
    met = sum(1 for i in review.items if i.met)
    ratio = met / len(rubric)
    if review.verdict == 'unclear':
        return 'unclear', ratio
    decided = 'pass' if ratio >= PASS_RATIO else 'fail'
    if review.verdict != decided:
        # 模型结论与逐条判定冲突：以逐条判定为准，但标记为需要人工确认
        return decided, ratio
    return decided, ratio


async def review_explain(*, concept_name: str, concept_summary: str, rubric: list[str],
                         text: str, gateway: ModelGateway | None = None) -> dict:
    """评审一段解释。返回结构化结果；调用方据此决定是否把 pending 落成 pass/fail。"""
    if not rubric:
        return {'verdict': 'unclear', 'ratio': 0.0, 'items': [], 'summary': '',
                'model': None, 'provider': None, 'degraded': False,
                'note': 'rubric 为空，无法评审'}
    gw = gateway or get_model_gateway()
    try:
        result = await gw.generate('grading', _build_messages(
            concept_name=concept_name, concept_summary=concept_summary,
            rubric=rubric, text=text), schema=ExplainReview)
    except SchemaValidationError as exc:
        return {'verdict': 'unclear', 'ratio': 0.0, 'items': [], 'summary': str(exc)[:500],
                'model': None, 'provider': None, 'degraded': True,
                'note': '模型输出不符合 schema，保留待人工评审'}

    review: ExplainReview = result.data
    verdict, ratio = _decide(review, rubric)
    degraded = result.provider_name == 'mock'
    if degraded:
        # 离线占位符没有判断能力，绝不允许它决定学习者过不过
        verdict = 'unclear'
    return {
        'verdict': verdict,
        'ratio': ratio,
        'items': [i.model_dump() for i in review.items],
        'summary': review.summary,
        'model': result.model_name,
        'provider': result.provider_name,
        'degraded': degraded,
        'note': '模型不可用，已降级为待人工评审' if degraded else '',
    }


def apply_review(db, submission_id: int, review: dict, *, reviewer: str = 'ai-teacher') -> dict:
    """把评审结果落库。unclear 不改变状态——仍然 pending，等人看。"""
    from ..domain import project as proj
    if review['verdict'] == 'unclear':
        return {'submission_id': submission_id, 'verdict': 'pending',
                'reason': review.get('note') or review.get('summary') or 'AI 无法判断'}
    approved = review['verdict'] == 'pass'
    note = json.dumps({'ratio': review['ratio'], 'items': review['items'],
                       'summary': review['summary'], 'model': review['model'],
                       'provider': review['provider']}, ensure_ascii=False)
    return proj.review_submission(db, submission_id, approved=approved,
                                  reviewer=reviewer, note=note)
