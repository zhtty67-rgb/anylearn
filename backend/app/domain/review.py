"""确定性 FSRS-6 间隔重复调度，由不可变作答记录投影重建。

移植自 gongkao-learning-os 并做两处通用化：
1. 投影按 pack_id 范围重建，多内容包互不干扰；
2. 支持 self_rate（自评卡片）题型：作答即自评，直接映射 FSRS 评分。
"""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid5, NAMESPACE_URL

from fsrs import Card, Rating, Scheduler

SCHEDULER_VERSION = 'py-fsrs-6.3.2'
RATING_POLICY_VERSION = 'anylearn-auto-rating-v1'

SCHEDULER = Scheduler(
    desired_retention=0.9,
    learning_steps=(),
    relearning_steps=(),
    maximum_interval=36500,
    enable_fuzzing=False,
)

SELF_RATINGS = {
    'again': (Rating.Again, 'self_again'),
    'hard': (Rating.Hard, 'self_hard'),
    'good': (Rating.Good, 'self_good'),
    'easy': (Rating.Easy, 'self_easy'),
}


def _card_id(question_id: str) -> int:
    return int.from_bytes(sha256(question_id.encode('utf-8')).digest()[:7], 'big')


def rating_for_attempt(attempt, estimated_seconds: int):
    """把作答表现映射为 FSRS 评分，学习者无需手动打分。"""
    qtype = attempt['qtype'] if 'qtype' in attempt.keys() else None
    if qtype == 'self_rate':
        return SELF_RATINGS.get(str(attempt['answer'] or '').strip().lower(), (Rating.Good, 'self_default'))
    if not attempt['correct']:
        return Rating.Again, 'incorrect'
    if attempt['hint_level'] > 0:
        return Rating.Hard, 'hint_used'
    if attempt['elapsed_ms'] > estimated_seconds * 1000:
        return Rating.Hard, 'over_time'
    conf = attempt['confidence']
    if conf is not None and conf <= 0.4:
        return Rating.Hard, 'low_confidence'
    if attempt['elapsed_ms'] <= estimated_seconds * 600 and conf is not None and conf >= 0.8:
        return Rating.Easy, 'fast_high_confidence'
    return Rating.Good, 'standard_correct'


def rebuild_reviews(db, pack_id: str | None = None):
    """重放全部（或单个内容包的）正式作答，重建 FSRS 卡片与事件投影。"""
    pack_filter = 'AND q.pack_id=?' if pack_id else ()
    rows = db.execute(
        f'''SELECT a.*, q.estimated_seconds, q.type AS qtype FROM attempts a
            JOIN questions q ON q.id=a.question_id
            WHERE a.submitted_at IS NOT NULL AND a.valid_for_stats=1 {pack_filter}
            ORDER BY a.question_id, a.submitted_at, a.id''',
        ((pack_id,) if pack_id else ()),
    ).fetchall()
    if pack_id:
        db.execute(
            'DELETE FROM review_events WHERE question_id IN (SELECT id FROM questions WHERE pack_id=?)', (pack_id,))
        db.execute(
            'DELETE FROM review_cards WHERE question_id IN (SELECT id FROM questions WHERE pack_id=?)', (pack_id,))
    else:
        db.execute('DELETE FROM review_events')
        db.execute('DELETE FROM review_cards')

    cards, counts, lapses = {}, {}, {}
    for attempt in rows:
        question_id = attempt['question_id']
        reviewed_at = datetime.fromisoformat(attempt['submitted_at']).astimezone(timezone.utc)
        card = cards.get(question_id) or Card(card_id=_card_id(question_id), due=reviewed_at)
        rating, reason = rating_for_attempt(attempt, attempt['estimated_seconds'])
        state_before, due_before = card.state.value, card.due.isoformat()
        had_prior = card.last_review is not None
        card, _ = SCHEDULER.review_card(
            card, rating, review_datetime=reviewed_at, review_duration=attempt['elapsed_ms'])
        cards[question_id] = card
        counts[question_id] = counts.get(question_id, 0) + 1
        lapses[question_id] = lapses.get(question_id, 0) + int(had_prior and rating is Rating.Again)
        db.execute(
            '''INSERT INTO review_events
               (id,attempt_id,question_id,rating,rating_reason,reviewed_at,elapsed_ms,
                state_before,state_after,due_before,due_after,stability_after,difficulty_after,
                created_at,scheduler_version,rating_policy_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (str(uuid5(NAMESPACE_URL, f'anylearn-review:{attempt["id"]}')), attempt['id'], question_id,
             rating.value, reason, reviewed_at.isoformat(), attempt['elapsed_ms'],
             state_before, card.state.value, due_before, card.due.isoformat(),
             card.stability, card.difficulty, attempt['submitted_at'],
             SCHEDULER_VERSION, RATING_POLICY_VERSION),
        )
    updated_at = datetime.now(timezone.utc).isoformat()
    for question_id, card in cards.items():
        db.execute(
            '''INSERT INTO review_cards
               (question_id,card_id,state,step,stability,difficulty,due,last_review,
                review_count,lapse_count,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (question_id, card.card_id, card.state.value, card.step or 0, card.stability, card.difficulty,
             card.due.isoformat(), card.last_review.isoformat() if card.last_review else None,
             counts[question_id], lapses[question_id], updated_at),
        )


def due_reviews(db, pack_id: str | None = None, as_of=None, limit: int = 25):
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pack_filter = 'AND q.pack_id=?' if pack_id else ''
    params: list = [as_of.isoformat()]
    if pack_id:
        params.append(pack_id)
    params.append(limit)
    return db.execute(
        f'''SELECT rc.question_id AS id, rc.state, rc.stability, rc.difficulty, rc.due, rc.last_review,
                   rc.review_count, rc.lapse_count, q.module_id, q.type, q.stem, q.options_json,
                   q.difficulty AS question_difficulty, q.estimated_seconds, q.pack_id
            FROM review_cards rc JOIN questions q ON q.id=rc.question_id
            WHERE rc.due<=? {pack_filter}
            ORDER BY rc.due, rc.question_id LIMIT ?''',
        params,
    ).fetchall()
