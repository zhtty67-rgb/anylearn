"""FSRS 复习投影与掌握度投影：由作答重建、评分映射、提示打折。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.mastery import overall_mastery, rebuild_mastery
from app.domain.quiz import create_session, submit_answer
from app.domain.review import due_reviews, rebuild_reviews


def test_review_cards_built_from_attempts(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', count=10)
    submit_answer(db, s['session_id'], 'q1', answer='A', elapsed_ms=3000)
    submit_answer(db, s['session_id'], 'q2', answer='nope', elapsed_ms=3000)
    cards = db.execute('SELECT * FROM review_cards').fetchall()
    assert {c['question_id'] for c in cards} == {'q1', 'q2'}
    q1_card = next(c for c in cards if c['question_id'] == 'q1')
    q2_card = next(c for c in cards if c['question_id'] == 'q2')
    # 答对的稳定性应高于答错的
    assert q1_card['stability'] > q2_card['stability']
    events = db.execute('SELECT * FROM review_events').fetchall()
    assert len(events) == 2


def test_due_returns_only_due(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', count=10)
    submit_answer(db, s['session_id'], 'q1', answer='A', elapsed_ms=3000)
    rows = due_reviews(db, pack_id='demo-pack', limit=10)
    # 刚答对的新卡不会立刻到期
    assert all(r['id'] != 'q1' for r in rows)


def test_self_rate_maps_directly_to_fsrs(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', count=10)
    submit_answer(db, s['session_id'], 'q3', answer='again')   # 自评：忘了
    ev = db.execute('SELECT rating, rating_reason FROM review_events WHERE question_id=?',
                    ('q3',)).fetchone()
    assert ev['rating'] == 1 and ev['rating_reason'] == 'self_again'


def test_confidence_low_correct_maps_hard(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', count=10)
    submit_answer(db, s['session_id'], 'q1', answer='A', confidence=0.2, elapsed_ms=3000)
    ev = db.execute('SELECT rating, rating_reason FROM review_events WHERE question_id=?',
                    ('q1',)).fetchone()
    assert ev['rating_reason'] == 'low_confidence'


def test_mastery_projection_and_hint_discount(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', module_ids=['mod-a'], count=10)
    submit_answer(db, s['session_id'], 'q1', answer='A', elapsed_ms=3000)                 # 独立做对
    s2 = create_session(db, 'demo-pack', module_ids=['mod-a'], count=10)
    submit_answer(db, s2['session_id'], 'q2', answer='dynasty', hint_level=2, elapsed_ms=3000)  # 二级提示后对
    node = db.execute(
        "SELECT ms.* FROM mastery_state ms JOIN knowledge_nodes kn ON kn.id=ms.knowledge_node_id "
        "WHERE kn.code='a-1-1'").fetchone()
    # 全对但一题用了二级提示：正证据 = 1.0 + 0.45，负证据 = 0
    assert node['positive_evidence'] == pytest.approx(1.45)
    assert node['negative_evidence'] == 0.0
    assert node['mastery_score'] == pytest.approx((1 + 1.45) / (2 + 1.45))
    assert 0 < overall_mastery(db, 'demo-pack') <= 1


def test_rebuild_is_deterministic_replay(installed_db):
    db = installed_db
    s = create_session(db, 'demo-pack', count=10)
    submit_answer(db, s['session_id'], 'q1', answer='A')
    before = db.execute('SELECT question_id, due, stability FROM review_cards ORDER BY question_id').fetchall()
    rebuild_reviews(db, pack_id='demo-pack')
    rebuild_mastery(db, pack_id='demo-pack')
    after = db.execute('SELECT question_id, due, stability FROM review_cards ORDER BY question_id').fetchall()
    assert [dict(b) for b in before] == [dict(a) for a in after]
