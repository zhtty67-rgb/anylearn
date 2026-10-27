"""做题引擎：组题、四种题型判分、空答案、信心、会话收尾。"""
import pytest

from app.domain.quiz import (
    create_session, grade, session_detail, session_result, submit_answer,
)


def _q(db, qid):
    return db.execute('SELECT * FROM questions WHERE id=?', (qid,)).fetchone()


def test_grading_single_choice_letter_and_text(installed_db):
    q = _q(installed_db, 'q1')
    assert grade(q, 'A') is True
    assert grade(q, 'a') is True
    assert grade(q, 'B') is False
    assert grade(q, 'dynasty') is True       # 直接答选项内容
    assert grade(q, 'realm') is False


def test_grading_cloze_alternatives(installed_db):
    q = _q(installed_db, 'q2')
    assert grade(q, 'dynasty') is True
    assert grade(q, ' Dynasty ') is True
    assert grade(q, 'dynastie') is False


def test_grading_self_rate(installed_db):
    q = _q(installed_db, 'q3')
    assert grade(q, 'good') is True
    assert grade(q, 'easy') is True
    assert grade(q, 'again') is False


def test_grading_short_answer(installed_db):
    q = _q(installed_db, 'q5')
    assert grade(q, 'information') is True
    assert grade(q, 'INFORMATION.') is True
    assert grade(q, '信息') is True
    assert grade(q, 'infos') is False


def test_empty_answer_counts_as_incorrect(installed_db):
    q = _q(installed_db, 'q1')
    assert grade(q, None) is False
    assert grade(q, '   ') is False


def test_create_session_filters_and_prefers_unseen(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', module_ids=['mod-a'], count=10)
    detail = session_detail(db, s['session_id'])
    assert {q['id'] for q in detail['questions']} == {'q1', 'q2'}
    assert all(q['module_id'] == 'mod-a' for q in detail['questions'])
    assert all('answer' not in q for q in detail['questions'])   # 不泄答案


def test_create_session_unknown_pack(installed_db):
    with pytest.raises(LookupError):
        create_session(installed_db, 'no-such-pack')


def test_submit_answer_full_flow(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', module_ids=['mod-a'], count=10)
    r1 = submit_answer(db, s['session_id'], 'q1', answer='A', confidence=0.9, elapsed_ms=5000)
    assert r1['correct'] is True and r1['answer'] == 'A'
    assert r1['remaining'] == 1 and not r1['session_finished']
    r2 = submit_answer(db, s['session_id'], 'q2', answer='wrong', confidence=0.2, elapsed_ms=90000)
    assert r2['correct'] is False and r2['session_finished']
    att = db.execute('SELECT * FROM attempts WHERE question_id=?', ('q1',)).fetchone()
    assert att['confidence'] == 0.9 and att['valid_for_stats'] == 1
    status = db.execute('SELECT status FROM quiz_sessions WHERE id=?', (s['session_id'],)).fetchone()
    assert status['status'] == 'finished'


def test_submit_answer_rejects_foreign_question(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', module_ids=['mod-a'], count=10)
    with pytest.raises(ValueError):
        submit_answer(db, s['session_id'], 'q4', answer='B')


def test_session_result(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', count=10)
    submit_answer(db, s['session_id'], 'q1', answer='A')
    submit_answer(db, s['session_id'], 'q2', answer='dynasty')
    submit_answer(db, s['session_id'], 'q3', answer='good')
    submit_answer(db, s['session_id'], 'q4', answer='A')     # 错
    submit_answer(db, s['session_id'], 'q5', answer=None)    # 空提交
    result = session_result(db, s['session_id'])
    assert result['total'] == 5 and result['correct'] == 3
    assert result['by_module']['mod-a'] == {'total': 2, 'correct': 2}
    assert result['by_module']['mod-b']['correct'] == 1


def test_grading_multi_choice(installed_db):
    """多选题：必须完全一致，少选/多选都判错。"""
    from types import SimpleNamespace
    q = {'type': 'multi_choice', 'answer': 'ABC',
         'options_json': '["甲","乙","丙","丁","戊"]'}
    assert grade(q, 'ABC') is True
    assert grade(q, 'abc') is True
    assert grade(q, 'CBA') is True          # 顺序无关
    assert grade(q, 'AB') is False           # 少选
    assert grade(q, 'ABCD') is False         # 多选
    assert grade(q, '') is False             # 空
    assert grade(q, None) is False


def test_multi_choice_pack_validation(db, tmp_path):
    """multi_choice 至少两个正确字母，且必须在选项范围内。"""
    import json as _json
    from app.contentpack.loader import PackValidationError, install_pack
    from tests.conftest import make_pack
    d = make_pack(tmp_path / 'mp', pack_id='multi-test', with_tree=False, questions=[{
        'id': 'm1', 'module': 'mod-a', 'type': 'multi_choice', 'stem': 's',
        'options': ['a', 'b', 'c'], 'answer': 'A',        # 只有一个字母 -> 非法
    }])
    with pytest.raises(PackValidationError):
        install_pack(db, d)
