"""学习概览统计：全部指标由内容包范围推导，不含任何领域语义。"""
from datetime import datetime, timezone

from .mastery import overall_mastery


def _accuracy(rows):
    total = len(rows)
    return (sum(1 for r in rows if r['correct']) / total) if total else None


def overview(db, pack_id: str) -> dict:
    pack = db.execute('SELECT * FROM packs WHERE id=?', (pack_id,)).fetchone()
    if pack is None:
        raise LookupError(f'内容包不存在: {pack_id}')
    question_total = db.execute('SELECT COUNT(*) c FROM questions WHERE pack_id=?', (pack_id,)).fetchone()['c']
    attempted = db.execute(
        '''SELECT DISTINCT a.question_id FROM attempts a JOIN questions q ON q.id=a.question_id
           WHERE q.pack_id=? AND a.valid_for_stats=1''', (pack_id,)).fetchall()
    attempt_rows = db.execute(
        '''SELECT a.correct, a.confidence FROM attempts a JOIN questions q ON q.id=a.question_id
           WHERE q.pack_id=? AND a.valid_for_stats=1 ORDER BY a.submitted_at DESC LIMIT 500''',
        (pack_id,)).fetchall()
    due_count = db.execute(
        '''SELECT COUNT(*) c FROM review_cards rc JOIN questions q ON q.id=rc.question_id
           WHERE q.pack_id=? AND rc.due<=?''',
        (pack_id, datetime.now(timezone.utc).isoformat())).fetchone()['c']
    streak_row = db.execute(
        '''SELECT COUNT(DISTINCT substr(a.submitted_at,1,10)) days FROM attempts a
           JOIN questions q ON q.id=a.question_id WHERE q.pack_id=? AND a.valid_for_stats=1''',
        (pack_id,)).fetchone()

    modules = []
    for m in db.execute('SELECT * FROM modules WHERE pack_id=? ORDER BY sort_no', (pack_id,)).fetchall():
        qcount = db.execute('SELECT COUNT(*) c FROM questions WHERE pack_id=? AND module_id=?',
                            (pack_id, m['id'])).fetchone()['c']
        seen = db.execute(
            '''SELECT COUNT(DISTINCT a.question_id) c FROM attempts a JOIN questions q ON q.id=a.question_id
               WHERE q.pack_id=? AND q.module_id=? AND a.valid_for_stats=1''',
            (pack_id, m['id'])).fetchone()['c']
        acc = _accuracy(db.execute(
            '''SELECT a.correct FROM attempts a JOIN questions q ON q.id=a.question_id
               WHERE q.pack_id=? AND q.module_id=? AND a.valid_for_stats=1''',
            (pack_id, m['id'])).fetchall())
        mastery_row = db.execute(
            '''SELECT AVG(ms.mastery_score) avg_m FROM mastery_state ms
               JOIN knowledge_nodes kn ON kn.id=ms.knowledge_node_id
               WHERE kn.pack_id=? AND kn.module_id=?''',
            (pack_id, m['id'])).fetchone()
        due_m = db.execute(
            '''SELECT COUNT(*) c FROM review_cards rc JOIN questions q ON q.id=rc.question_id
               WHERE q.pack_id=? AND q.module_id=? AND rc.due<=?''',
            (pack_id, m['id'], datetime.now(timezone.utc).isoformat())).fetchone()['c']
        modules.append({
            'id': m['id'], 'name': m['name'], 'questions': qcount, 'attempted': seen,
            'accuracy': acc, 'mastery': mastery_row['avg_m'] if mastery_row and mastery_row['avg_m'] is not None else None,
            'due': due_m,
        })

    confidences = [r['confidence'] for r in attempt_rows if r['confidence'] is not None]
    return {
        'pack_id': pack_id,
        'pack_name': pack['name'],
        'questions': question_total,
        'attempted_questions': len(attempted),
        'attempts': len(attempt_rows),
        'accuracy': _accuracy(attempt_rows),
        'overall_mastery': overall_mastery(db, pack_id),
        'due_reviews': due_count,
        'active_days': streak_row['days'] if streak_row else 0,
        'confidence_reported_ratio': len(confidences) / len(attempt_rows) if attempt_rows else None,
        'modules': modules,
    }
