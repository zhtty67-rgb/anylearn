"""项目层测试：门禁、产物验收、等级联动。

核心断言：**做题做得好只能到 L3；L4/L5 必须靠真实产物验收。**
"""
import json
import sys

import pytest

from app.domain import lesson, project as proj


def _seed(db, pack='demo-pack'):
    now = '2026-01-01T00:00:00Z'
    db.execute("INSERT INTO concepts (id,pack_id,code,module_id,name,summary,misconceptions_json,created_at)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (f'{pack}:c1', pack, 'c1', 'mod-a', '过拟合', '定义', '[]', now))
    db.execute("INSERT INTO courses (id,pack_id,code,title,goal,audience,version,created_at)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (f'{pack}:course', pack, 'course', '课程', '', '', '1.0.0', now))
    db.execute("INSERT INTO course_units (id,course_id,code,title,objective,sort_no,est_minutes)"
               " VALUES (?,?,?,?,?,?,?)", (f'{pack}:u1', f'{pack}:course', 'u1', '单元一', '', 1, 30))
    db.execute("INSERT INTO unit_concepts (unit_id,concept_id,target_level,role) VALUES (?,?,3,'core')",
               (f'{pack}:u1', f'{pack}:c1'))
    db.execute("INSERT INTO projects (id,pack_id,code,title,brief,goal,authored_by,created_at)"
               " VALUES (?,?,?,?,?,?,'content',?)",
               (f'{pack}:p1', pack, 'p1', '资料问答助手', '做一个带出处的问答', '验证 RAG 能力', now))
    db.execute("INSERT INTO project_requirements (project_id,unit_id,min_level) VALUES (?,?,3)",
               (f'{pack}:p1', f'{pack}:u1'))
    db.execute("INSERT INTO project_milestones (id,project_id,code,title,objective,sort_no,est_minutes)"
               " VALUES (?,?,?,?,?,?,?)", (f'{pack}:p1:m1', f'{pack}:p1', 'm1', '里程碑一', '能跑', 1, 60))
    db.execute("INSERT INTO project_concepts (project_id,concept_id,target_level) VALUES (?,?,4)",
               (f'{pack}:p1', f'{pack}:c1'))


def _add_deliverable(db, code, kind, acceptance, required=1, ms='m1', pack='demo-pack'):
    did = f'{pack}:p1:{ms}:{code}'
    db.execute("INSERT INTO project_deliverables (id,milestone_id,code,title,kind,required,"
               "acceptance_json,sort_no) VALUES (?,?,?,?,?,?,?,?)",
               (did, f'{pack}:p1:{ms}', code, code, kind, required,
                json.dumps(acceptance, ensure_ascii=False), 1))
    return did


@pytest.fixture
def pdb(installed_db):
    _seed(installed_db)
    return installed_db


# ---------------------------------------------------------------- 门禁
def test_gate_locked_until_prerequisite_unit_met(pdb):
    gate = proj.project_gate(pdb, 'demo-pack:p1')
    assert gate['open'] is False
    assert gate['missing'][0]['title'] == '单元一'
    assert gate['missing'][0]['short'][0]['concept'] == '过拟合'


def test_gate_opens_after_unit_concept_reaches_target(pdb):
    cid = 'demo-pack:c1'
    lesson.record_event(pdb, 'demo-pack', 'self_explain', concept_id=cid, assisted=0)
    for _ in range(2):
        lesson.record_event(pdb, 'demo-pack', 'attempt', concept_id=cid, assisted=0)
    lesson.rebuild_ability(pdb, 'demo-pack')
    assert proj.project_gate(pdb, 'demo-pack:p1')['open'] is True


# ---------------------------------------------------------------- 产物检查
def test_file_deliverable_checks_existence_and_size(pdb, tmp_path):
    did = _add_deliverable(pdb, 'd-file', 'file', {'path': 'main.py', 'min_bytes': 10})
    (tmp_path / 'main.py').write_text('print("hi")\n' * 3, encoding='utf-8')
    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path)
    assert res['ok'] is True

    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path / 'empty')
    assert res['ok'] is False


def test_file_deliverable_rejects_path_escape(pdb, tmp_path):
    did = _add_deliverable(pdb, 'd-esc', 'file', {'path': '../secret.txt'})
    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path)
    assert res['ok'] is False
    assert '越界' in res['checks'][0]['detail']


def test_run_deliverable_checks_exit_code_and_stdout(pdb, tmp_path):
    did = _add_deliverable(pdb, 'd-run', 'run',
                           {'cmd': f'"{sys.executable}" -c "print(\'ok-123\')"',
                            'expect_exit': 0, 'expect_stdout_contains': 'ok-123'})
    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path)
    assert res['ok'] is True

    bad = _add_deliverable(pdb, 'd-run2', 'run',
                           {'cmd': f'"{sys.executable}" -c "print(\'nope\')"',
                            'expect_stdout_contains': 'ok-123'})
    assert proj.evaluate_deliverable(pdb, bad, artifact_base=tmp_path)['ok'] is False


def test_test_deliverable_uses_exit_code(pdb, tmp_path):
    (tmp_path / 'test_ok.py').write_text('def test_x():\n    assert 1 + 1 == 2\n', encoding='utf-8')
    did = _add_deliverable(pdb, 'd-test', 'test', {'cmd': f'"{sys.executable}" -m pytest -q'})
    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path)
    assert res['ok'] is True, res


def test_data_deliverable_reads_json_value(pdb, tmp_path):
    (tmp_path / 'result.json').write_text(json.dumps({'accuracy': 0.91}), encoding='utf-8')
    did = _add_deliverable(pdb, 'd-data', 'data',
                           {'path': 'result.json', 'jsonpath': '$.accuracy', 'min': 0.8})
    assert proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path)['ok'] is True

    (tmp_path / 'result.json').write_text(json.dumps({'accuracy': 0.5}), encoding='utf-8')
    assert proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path)['ok'] is False


def test_explain_deliverable_never_auto_grades_semantics(pdb, tmp_path):
    did = _add_deliverable(pdb, 'd-exp', 'explain',
                           {'rubric': ['概念正确', '举例恰当'], 'min_chars': 10})
    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path,
                                    payload={'explain': '过拟合就是记住了噪声，比如把曲线扭得很弯。'})
    assert res['checks'][0]['needs_review'] is True
    assert res['checks'][0]['rubric'] == ['概念正确', '举例恰当']
    # 结构合格但语义未评审 → pending，不是 pass 也不是 fail
    assert res['verdict'] == 'pending'


def test_explain_too_short_is_fail_not_pending(pdb, tmp_path):
    did = _add_deliverable(pdb, 'd-exp2', 'explain', {'min_chars': 100, 'rubric': ['x']})
    res = proj.evaluate_deliverable(pdb, did, artifact_base=tmp_path,
                                    payload={'explain': '太短'})
    assert res['verdict'] == 'fail'


def test_pending_does_not_complete_milestone_until_reviewed(pdb, tmp_path):
    ok = _add_deliverable(pdb, 'd-ok', 'run',
                          {'cmd': f'"{sys.executable}" -c "print(1)"', 'expect_exit': 0})
    exp = _add_deliverable(pdb, 'd-exp3', 'explain', {'min_chars': 5, 'rubric': ['x']})
    proj.submit_deliverable(pdb, ok, artifact_base=tmp_path)
    res = proj.submit_deliverable(pdb, exp, artifact_base=tmp_path,
                                  payload={'explain': '这是一段足够长的解释文本内容。'})
    assert res['verdict'] == 'pending'
    assert proj.project_status(pdb, 'demo-pack:p1')['milestones'][0]['passed'] is False
    assert proj.project_status(pdb, 'demo-pack:p1')['status'] == 'in_review'

    sub_id = pdb.execute("SELECT id FROM deliverable_submissions WHERE verdict='pending'"
                         ).fetchone()['id']
    proj.review_submission(pdb, sub_id, approved=True, reviewer='teacher')
    st = proj.project_status(pdb, 'demo-pack:p1')
    assert st['milestones'][0]['passed'] is True and st['completed'] is True


# ---------------------------------------------------------------- 等级联动
def _level(db, cid='demo-pack:c1'):
    row = db.execute('SELECT level FROM concept_ability WHERE concept_id=?', (cid,)).fetchone()
    return row['level'] if row else 0


def test_doing_exercises_caps_at_L4_without_project(pdb, tmp_path):
    """纯做题能推到 L4，但 L5 必须靠项目验收兑现。"""
    cid = 'demo-pack:c1'
    lesson.record_event(pdb, 'demo-pack', 'self_explain', concept_id=cid, assisted=0)
    for _ in range(10):
        lesson.record_event(pdb, 'demo-pack', 'attempt', concept_id=cid, assisted=0)
    lesson.rebuild_ability(pdb, 'demo-pack')
    assert _level(pdb) == 4

    did = _add_deliverable(pdb, 'd-run3', 'run',
                           {'cmd': f'"{sys.executable}" -c "print(1)"', 'expect_exit': 0})
    proj.submit_deliverable(pdb, did, artifact_base=tmp_path)
    assert _level(pdb) == 5


def test_failed_project_does_not_advance_level(pdb, tmp_path):
    cid = 'demo-pack:c1'
    did = _add_deliverable(pdb, 'd-fail', 'file', {'path': 'missing.py'})
    proj.submit_deliverable(pdb, did, artifact_base=tmp_path)
    row = pdb.execute('SELECT failures FROM concept_ability WHERE concept_id=?', (cid,)).fetchone()
    assert _level(pdb) == 0
    assert row['failures'] >= 1


def test_assisted_project_pass_does_not_count_as_verify(pdb, tmp_path):
    cid = 'demo-pack:c1'
    did = _add_deliverable(pdb, 'd-asst', 'run',
                           {'cmd': f'"{sys.executable}" -c "print(1)"', 'expect_exit': 0})
    proj.submit_deliverable(pdb, did, artifact_base=tmp_path, assisted=True)
    row = pdb.execute('SELECT independent_passes, assisted_passes FROM concept_ability '
                      'WHERE concept_id=?', (cid,)).fetchone()
    assert row['independent_passes'] == 0
    assert row['assisted_passes'] >= 1


# ---------------------------------------------------------------- 状态
def test_milestone_and_project_complete(pdb, tmp_path):
    did = _add_deliverable(pdb, 'd-ok', 'run',
                           {'cmd': f'"{sys.executable}" -c "print(1)"', 'expect_exit': 0})
    proj.submit_deliverable(pdb, did, artifact_base=tmp_path)
    st = proj.project_status(pdb, 'demo-pack:p1')
    assert st['milestones'][0]['passed'] is True
    assert st['completed'] is True
    assert st['status'] == 'completed'


def test_optional_deliverable_does_not_block_milestone(pdb, tmp_path):
    _add_deliverable(pdb, 'd-req', 'run',
                     {'cmd': f'"{sys.executable}" -c "print(1)"', 'expect_exit': 0}, required=1)
    _add_deliverable(pdb, 'd-opt', 'file', {'path': 'nope.md'}, required=0)
    proj.submit_deliverable(pdb, 'demo-pack:p1:m1:d-req', artifact_base=tmp_path)
    assert proj.project_status(pdb, 'demo-pack:p1')['milestones'][0]['passed'] is True


def test_user_project_can_be_registered(pdb):
    res = proj.user_project(pdb, 'demo-pack', code='my-rag', title='我的问答助手',
                            brief='', goal='', repo_path='D:/myproj')
    row = pdb.execute('SELECT authored_by, repo_path FROM projects WHERE id=?',
                      (res['project_id'],)).fetchone()
    assert row['authored_by'] == 'user' and row['repo_path'] == 'D:/myproj'


def test_unknown_project_raises(pdb):
    with pytest.raises(KeyError):
        proj.project_gate(pdb, 'nope')
