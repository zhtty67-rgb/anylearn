"""学习框架逻辑测试：定级、卡点诊断、单元推进。

覆盖要点：
1. 等级只能由真实证据推进，辅助通过不推进
2. 误解命中会压低天花板
3. 卡点诊断能给出具体依据，而不是一个百分比
4. 重放重建幂等（同一批事件重算两次结果一致）
"""
import json

import pytest

from app.domain import lesson
from app.contentpack.loader import install_pack


PACK = 'demo-pack'


def _seed(db, pack_id=PACK, prereq_ok=False):
    """在演示包里加概念、先修、课程、单元与步骤。"""
    now = '2026-01-01T00:00:00Z'
    db.execute("INSERT OR IGNORE INTO concepts (id,pack_id,code,module_id,name,summary,misconceptions_json,created_at)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (f'{pack_id}:c-train-test', pack_id, 'c-train-test', 'mod-b', '训练集与测试集',
                '训练集用来拟合，测试集只能用于评估', json.dumps(['以为训练准确率高就代表泛化好'], ensure_ascii=False), now))
    db.execute("INSERT OR IGNORE INTO concepts (id,pack_id,code,module_id,name,summary,misconceptions_json,created_at)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (f'{pack_id}:c-overfit', pack_id, 'c-overfit', 'mod-b', '过拟合',
                '模型记住了训练数据的噪声，换新数据就失效', '[]', now))
    # 过拟合的先修是「训练集与测试集」
    db.execute("INSERT OR IGNORE INTO concept_prerequisites (concept_id,prerequisite_id,strength)"
               " VALUES (?,?,1.0)",
               (f'{pack_id}:c-overfit', f'{pack_id}:c-train-test'))
    db.execute("INSERT OR IGNORE INTO courses (id,pack_id,code,title,goal,version,created_at)"
               " VALUES (?,?,?,?,?,?,?)",
               (f'{pack_id}:course-1', pack_id, 'course-1', '机器学习入门', '能判断模型是否过拟合', '1.0.0', now))
    db.execute("INSERT OR IGNORE INTO course_units (id,course_id,code,title,objective,sort_no,est_minutes)"
               " VALUES (?,?,?,?,?,?,?)",
               (f'{pack_id}:u1', f'{pack_id}:course-1', 'u1', '第一单元', '独立判断过拟合并解释', 1, 40))
    db.execute("INSERT OR IGNORE INTO unit_concepts (unit_id,concept_id,target_level,role)"
               " VALUES (?,?,?,?)", (f'{pack_id}:u1', f'{pack_id}:c-overfit', 3, 'core'))
    for i, kind in enumerate(['diagnose', 'explain', 'socratic', 'practice', 'verify'], start=1):
        db.execute("INSERT OR IGNORE INTO unit_steps (id,unit_id,ord,kind,concept_id,title,config_json)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (f'{pack_id}:u1:s{i}', f'{pack_id}:u1', i, kind, f'{pack_id}:c-overfit',
                    f'步骤{i}', '{}'))


@pytest.fixture
def seeded(installed_db):
    _seed(installed_db)
    return installed_db


def _level(db, code, pack=PACK):
    row = db.execute('SELECT level FROM concept_ability WHERE concept_id=?',
                     (f'{pack}:{code}',)).fetchone()
    return row['level'] if row else 0


# ---------------------------------------------------------------- 定级
def test_no_events_means_level_zero(seeded):
    assert _level(seeded, 'c-overfit') == 0


def test_single_independent_attempt_gives_L1(seeded):
    lesson.record_event(seeded, PACK, 'attempt', concept_id=f'{PACK}:c-overfit', assisted=0)
    lesson.rebuild_ability(seeded, PACK)
    assert _level(seeded, 'c-overfit') == 1


def test_assisted_passes_do_not_advance(seeded):
    for _ in range(5):
        lesson.record_event(seeded, PACK, 'attempt', concept_id=f'{PACK}:c-overfit', hint_level=2)
    lesson.rebuild_ability(seeded, PACK)
    assert _level(seeded, 'c-overfit') == 0  # 只有辅助证据，等级不上去
    row = seeded.execute('SELECT assisted_passes, independent_passes FROM concept_ability'
                         ' WHERE concept_id=?', (f'{PACK}:c-overfit',)).fetchone()
    assert row['assisted_passes'] == 5 and row['independent_passes'] == 0


def test_full_ladder_reaches_L5(seeded):
    cid = f'{PACK}:c-overfit'
    lesson.record_event(seeded, PACK, 'attempt', concept_id=cid, assisted=0)   # L1
    lesson.record_event(seeded, PACK, 'self_explain', concept_id=cid, assisted=0)  # L2
    lesson.record_event(seeded, PACK, 'attempt', concept_id=cid, assisted=0)   # L3 需 2 次
    lesson.record_event(seeded, PACK, 'attempt', concept_id=cid, assisted=0)   # L4 需 3 次
    lesson.record_event(seeded, PACK, 'verify_pass', concept_id=cid, assisted=0)  # L5 需 4 次
    lesson.rebuild_ability(seeded, PACK)
    assert _level(seeded, 'c-overfit') == 5


def test_misconception_caps_level_4(seeded):
    cid = f'{PACK}:c-overfit'
    lesson.record_event(seeded, PACK, 'self_explain', concept_id=cid, assisted=0)
    for _ in range(4):
        lesson.record_event(seeded, PACK, 'attempt', concept_id=cid, assisted=0)
    lesson.rebuild_ability(seeded, PACK)
    assert _level(seeded, 'c-overfit') == 4
    lesson.record_event(seeded, PACK, 'misconception_hit', concept_id=cid)
    lesson.rebuild_ability(seeded, PACK)
    assert _level(seeded, 'c-overfit') == 3  # 有误解未消除，天花板压低


def test_rebuild_is_idempotent(seeded):
    cid = f'{PACK}:c-overfit'
    lesson.record_event(seeded, PACK, 'attempt', concept_id=cid, assisted=0)
    lesson.rebuild_ability(seeded, PACK)
    first = _level(seeded, 'c-overfit')
    lesson.rebuild_ability(seeded, PACK)
    assert _level(seeded, 'c-overfit') == first


# ---------------------------------------------------------------- 诊断
def test_diagnose_reports_prerequisite_gap(seeded):
    d = lesson.diagnose_blocker(seeded, f'{PACK}:c-overfit')
    codes = {r['code'] for r in d['reasons']}
    assert 'prerequisite_gap' in codes
    assert d['blocked'] is True
    assert '训练集与测试集' in d['reasons'][0]['detail']


def test_diagnose_reports_hint_dependency(seeded):
    cid = f'{PACK}:c-overfit'
    lesson.record_event(seeded, PACK, 'attempt', concept_id=cid, hint_level=1)
    lesson.rebuild_ability(seeded, PACK)
    d = lesson.diagnose_blocker(seeded, cid)
    codes = {r['code'] for r in d['reasons']}
    assert 'hint_dependency' in codes


def test_diagnose_reports_misconception(seeded):
    cid = f'{PACK}:c-overfit'
    lesson.record_event(seeded, PACK, 'misconception_hit', concept_id=cid)
    lesson.rebuild_ability(seeded, PACK)
    d = lesson.diagnose_blocker(seeded, cid)
    assert 'misconception' in {r['code'] for r in d['reasons']}


def test_diagnose_unknown_concept_raises(seeded):
    with pytest.raises(KeyError):
        lesson.diagnose_blocker(seeded, 'nope')


# ---------------------------------------------------------------- 推进
def test_advance_unit_tracks_steps_and_targets(seeded):
    unit = f'{PACK}:u1'
    status = lesson.unit_status(seeded, unit)
    assert status['steps_done'] == 0 and status['steps_total'] == 5
    assert status['all_targets_met'] is False

    for i in range(1, 6):
        status = lesson.advance_unit(seeded, unit, f'{PACK}:u1:s{i}', pack_id=PACK)
    assert status['steps_done'] == 5
    assert status['next_step'] is None
    # 步骤走完但概念没到 L3，单元不算达标
    assert status['all_targets_met'] is False


def test_next_unit_points_at_unfinished(seeded):
    nxt = lesson.next_unit(seeded, f'{PACK}:course-1')
    assert nxt is not None and nxt['unit_id'] == f'{PACK}:u1'
