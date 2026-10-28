"""AI 教师评审器与追问的测试。

核心断言：
1. 评审必须逐条覆盖 rubric，缺条 → 不判通过。
2. mock/离线 provider **永远不判定学习者过没过**，保持 pending。
3. 追问只产出一个问题，且不包含任何等级。
"""
import asyncio
import json
import sys

import pytest

from app.ai import reviewer, tutor
from app.ai.gateway import ModelGateway
from app.ai.schemas import GatewayConfig, Message, ModelPolicyConfig
from app.domain import project as proj

RUBRIC = ['指出训练/测试误差差异', '说明 U 形上升', '举例恰当', '说明局限']


class ScriptedProvider:
    """按预设返回固定 JSON 的 provider，用来验证判定逻辑本身。"""

    def __init__(self, payload: dict):
        self.payload = payload

    async def generate(self, messages: list[Message], config: ModelPolicyConfig,
                       json_mode: bool = False):
        text = json.dumps(self.payload, ensure_ascii=False)
        return text, len(text)


def _gateway(payload: dict, provider='scripted'):
    cfg = GatewayConfig(
        policies={k: ModelPolicyConfig(provider=provider, model=f'{provider}-m',
                                       temperature=0.0, max_tokens=2048)
                  for k in ('FAST', 'BALANCED', 'STRONG')},
        task_policy_map={'grading': 'STRONG', 'feynman_review': 'STRONG',
                         'socratic_probe': 'BALANCED'},
    )
    return ModelGateway(config=cfg, custom_provider=ScriptedProvider(payload))


def _review_payload(met_flags, verdict='pass'):
    return {'verdict': verdict,
            'items': [{'item': r, 'met': m, 'reason': '依据原文'}
                      for r, m in zip(RUBRIC, met_flags)],
            'summary': '总结'}


def _review(gw, text='一段解释', rubric=RUBRIC):
    return asyncio.run(reviewer.review_explain(
        concept_name='过拟合', concept_summary='', rubric=rubric, text=text, gateway=gw))


# ---------------------------------------------------------------- 评审判定
def test_review_all_met_passes():
    res = _review(_gateway(_review_payload([True] * 4)))
    assert res['verdict'] == 'pass' and res['ratio'] == 1.0
    assert len(res['items']) == 4


def test_review_partial_fails():
    res = _review(_gateway(_review_payload([True, False, False, False], verdict='fail')))
    assert res['verdict'] == 'fail' and res['ratio'] == 0.25


def test_review_missing_items_is_unclear_not_pass():
    """模型少给一条判定 → 不能算通过。"""
    res = _review(_gateway(_review_payload([True, True, True])))
    assert res['verdict'] == 'unclear'


def test_review_verdict_conflict_uses_items():
    """模型说 pass 但逐条只有一条满足 → 以逐条为准判 fail。"""
    res = _review(_gateway(_review_payload([True, False, False, False], verdict='pass')))
    assert res['verdict'] == 'fail'


def test_empty_rubric_is_unclear():
    res = _review(_gateway({}), rubric=[])
    assert res['verdict'] == 'unclear'


def test_mock_provider_never_decides():
    """provider 是 mock 时，即使返回 pass 也必须降成 unclear。"""
    res = _review(_gateway(_review_payload([True] * 4, verdict='pass'), provider='mock'))
    assert res['verdict'] == 'unclear'
    assert res['degraded'] is True


# ---------------------------------------------------------------- 追问
def test_socratic_returns_single_question():
    gw = _gateway({'question': '如果训练集全对，能说明学会了吗？',
                   'targets': '训练误差=能力', 'why': '击中常见误解'})
    res = asyncio.run(tutor.socratic_probe(
        concept={'name': '过拟合', 'summary': '定义'},
        misconceptions=['训练准确率高就是好模型'],
        utterance='训练集准确率 99%，所以模型很好。', gateway=gw))
    assert '？' in res['question'] or '?' in res['question']
    assert 'level' not in res


def test_feynman_review_reports_gaps_not_grades():
    gw = _gateway({'verdict': 'fail',
                   'items': [{'item': '讲清含义', 'met': True, 'reason': '有'},
                             {'item': '举例', 'met': False, 'reason': '无例子'}],
                   'gaps': ['缺少一个具体例子']})
    res = asyncio.run(tutor.feynman_review(
        concept={'name': '过拟合', 'summary': '定义'},
        rubric=['讲清含义', '举例'],
        explanation='过拟合就是学过头了。', gateway=gw))
    assert res['verdict'] == 'fail' and res['gaps'] == ['缺少一个具体例子']
    assert 'score' not in res and 'level' not in res


# ---------------------------------------------------------------- 落库联动
@pytest.fixture
def pdb_like(installed_db, tmp_path):
    from tests.test_project import _seed
    _seed(installed_db)
    return installed_db, tmp_path


def _add(db, code, kind, acceptance, required=1):
    did = f'demo-pack:p1:m1:{code}'
    db.execute("INSERT INTO project_deliverables (id,milestone_id,code,title,kind,required,"
               "acceptance_json,sort_no) VALUES (?,?,?,?,?,?,?,?)",
               (did, 'demo-pack:p1:m1', code, code, kind, required,
                json.dumps(acceptance, ensure_ascii=False), 1))
    return did


def test_apply_review_unclear_keeps_pending(pdb_like):
    db, art = pdb_like
    did = _add(db, 'd-airev', 'explain', {'min_chars': 5, 'rubric': RUBRIC})
    sub = proj.submit_deliverable(db, did, artifact_base=art,
                                  payload={'explain': '一段足够长的解释文本内容。'})
    assert sub['verdict'] == 'pending'
    sid = db.execute("SELECT id FROM deliverable_submissions WHERE verdict='pending'"
                     ).fetchone()['id']
    out = reviewer.apply_review(db, sid, {
        'verdict': 'unclear', 'ratio': 0.0, 'items': [], 'summary': '',
        'model': 'm', 'provider': 'mock', 'degraded': True, 'note': '模型不可用'})
    assert out['verdict'] == 'pending'
    still = db.execute('SELECT verdict FROM deliverable_submissions WHERE id=?',
                       (sid,)).fetchone()
    assert still['verdict'] == 'pending'


def test_apply_review_pass_completes_milestone(pdb_like):
    db, art = pdb_like
    did = _add(db, 'd-ok9', 'run',
               {'cmd': f'"{sys.executable}" -c "print(1)"', 'expect_exit': 0})
    exp = _add(db, 'd-exp9', 'explain', {'min_chars': 5, 'rubric': RUBRIC})
    proj.submit_deliverable(db, did, artifact_base=art)
    proj.submit_deliverable(db, exp, artifact_base=art,
                            payload={'explain': '足够长的解释文本。'})
    sid = db.execute("SELECT id FROM deliverable_submissions WHERE verdict='pending'"
                     ).fetchone()['id']
    out = reviewer.apply_review(db, sid, {
        'verdict': 'pass', 'ratio': 1.0,
        'items': [{'item': r, 'met': True, 'reason': 'ok'} for r in RUBRIC],
        'summary': '讲清楚了', 'model': 'strong-m', 'provider': 'openai_compatible',
        'degraded': False, 'note': ''})
    assert out['verdict'] == 'pass'
    assert proj.project_status(db, 'demo-pack:p1')['completed'] is True
