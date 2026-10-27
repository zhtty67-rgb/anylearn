"""端到端：一次完整的学习闭环。

模拟真实学习者走完「诊断 → 追问 → 讲解 → 费曼 → 动手 → 独立验收」，
验证框架能：
1. 从内容包装载的课程里找到该学的单元
2. 逐步推进，中途能诊断出卡点
3. 只靠辅助证据拿不到等级，独立证据才推进
4. 概念达标 + 步骤走完才算单元完成
"""
import json

import pytest

from app.contentpack.loader import install_pack
from app.domain import lesson

DEMO = {'concepts': [
    {'code': 'split', 'name': '训练集与测试集', 'module_id': 'mod-a', 'summary': '分开用',
     'misconceptions': ['用测试集调参']},
    {'code': 'overfit', 'name': '过拟合', 'module_id': 'mod-a', 'summary': '记住噪声',
     'prerequisites': ['split']}],
  'courses': [{'code': 'ml', 'title': '机器学习入门', 'goal': '能判断过拟合',
               'units': [{'code': 'u1', 'title': '过拟合单元', 'objective': '能独立判断',
                          'est_minutes': 30,
                          'concepts': [{'code': 'split', 'role': 'prereq', 'target_level': 1},
                                       {'code': 'overfit', 'role': 'core', 'target_level': 3}],
                          'steps': [
                              {'kind': 'diagnose', 'concept': 'overfit'},
                              {'kind': 'socratic', 'concept': 'overfit'},
                              {'kind': 'explain', 'concept': 'overfit'},
                              {'kind': 'feynman', 'concept': 'overfit'},
                              {'kind': 'verify', 'concept': 'overfit'},
                          ]}]}]}


@pytest.fixture
def pack_db(db, content_root):
    (content_root / 'demo-pack' / 'data' / 'curriculum.json').write_text(
        json.dumps(DEMO, ensure_ascii=False), encoding='utf-8')
    install_pack(db, content_root / 'demo-pack')
    return db


def test_full_learning_loop(pack_db):
    db = pack_db
    unit = 'demo-pack:ml:u1'
    cid = 'demo-pack:overfit'

    # 1. 找到该学的单元
    nxt = lesson.next_unit(db, 'demo-pack:ml')
    assert nxt['unit_id'] == unit and nxt['steps_done'] == 0

    # 2. 一开始就诊断：先修没达标，应指出「训练集与测试集」
    d = lesson.diagnose_blocker(db, cid)
    assert 'prerequisite_gap' in {r['code'] for r in d['reasons']}
    assert '先补先修' in d['next_action']

    # 3. 先修概念先到 L1：仍低于本单元核心概念所需的 L3，先修依旧挡路
    lesson.record_event(db, 'demo-pack', 'attempt', concept_id='demo-pack:split', assisted=0)
    lesson.rebuild_ability(db, 'demo-pack')
    d = lesson.diagnose_blocker(db, cid)
    gap = next(r for r in d['reasons'] if r['code'] == 'prerequisite_gap')
    assert gap['required_level'] == 3   # 目标等级来自单元的 core 概念，是显式规则
    assert gap['prerequisites'][0]['level'] == 1

    # 4. 先修补齐到 L3 后，先修不再挡路
    lesson.record_event(db, 'demo-pack', 'self_explain', concept_id='demo-pack:split', assisted=0)
    for _ in range(2):
        lesson.record_event(db, 'demo-pack', 'attempt', concept_id='demo-pack:split', assisted=0)
    lesson.rebuild_ability(db, 'demo-pack')
    d = lesson.diagnose_blocker(db, cid)
    assert 'prerequisite_gap' not in {r['code'] for r in d['reasons']}

    # 4. 在提示下做对，等级不推进（独立证据才算）
    lesson.record_event(db, 'demo-pack', 'attempt', concept_id=cid, hint_level=2)
    lesson.rebuild_ability(db, 'demo-pack')
    assert lesson.diagnose_blocker(db, cid)['level'] == 0
    assert 'hint_dependency' in {r['code'] for r in lesson.diagnose_blocker(db, cid)['reasons']}

    # 5. 走完步骤（这一步只记录「看过」，不代替作答）
    for i in range(1, 6):
        status = lesson.advance_unit(db, unit, f'{unit}:s{i}', pack_id='demo-pack')
    assert status['steps_done'] == 5 and status['next_step'] is None
    assert status['all_targets_met'] is False  # 步骤走完但概念没到 L3

    # 6. 补齐独立证据：解释 + 三次独立作答
    lesson.record_event(db, 'demo-pack', 'self_explain', concept_id=cid, assisted=0)
    for _ in range(3):
        lesson.record_event(db, 'demo-pack', 'attempt', concept_id=cid, assisted=0)
    lesson.rebuild_ability(db, 'demo-pack')
    assert lesson.diagnose_blocker(db, cid)['level'] >= 3

    status = lesson.advance_unit(db, unit, f'{unit}:s5', pack_id='demo-pack')
    assert status['all_targets_met'] is True

    # 7. 单元达标后，next_unit 不再指向它
    assert lesson.next_unit(db, 'demo-pack:ml') is None


def test_misconception_blocks_diagnosis(pack_db):
    db = pack_db
    cid = 'demo-pack:overfit'
    # 先补齐先修，让误解成为首要卡点
    lesson.record_event(db, 'demo-pack', 'self_explain', concept_id='demo-pack:split', assisted=0)
    for _ in range(2):
        lesson.record_event(db, 'demo-pack', 'attempt', concept_id='demo-pack:split', assisted=0)
    lesson.record_event(db, 'demo-pack', 'misconception_hit', concept_id=cid,
                        payload={'matched': '用测试集调参'})
    lesson.rebuild_ability(db, 'demo-pack')
    d = lesson.diagnose_blocker(db, cid)
    assert 'misconception' in {r['code'] for r in d['reasons']}
    assert '苏格拉底' in d['next_action']
