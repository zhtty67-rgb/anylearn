"""做题引擎：组会话、通用判分、作答落库。

判分与题型完全由内容包决定，框架不预设任何学科规则：
- single_choice: answer 为选项字母（A..H）
- cloze / short_answer: answer 为文本，支持 "|" 分隔多个可接受答案
- self_rate: answer 为 again/hard/good/easy 自评
空答案允许正式提交（记为未作答，进入复习调度）——沿用公考系统 v034 语义。
"""
import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

LETTERS = 'ABCDEFGH'


def _norm(text) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip().lower()


def _norm_loose(text) -> str:
    return re.sub(r'[\s，。！？；、,.!?;:\'"]+', '', _norm(text))


def grade(question, answer) -> bool:
    """对单题判分。answer 为 None/空串视为未作答，判错。"""
    if answer is None or not str(answer).strip():
        return False
    qtype = question['type']
    ans = str(answer).strip()
    if qtype == 'single_choice':
        correct_letter = str(question['answer']).strip().upper()
        idx = LETTERS.find(correct_letter)
        options = json.loads(question['options_json'] or '[]')
        correct_text = options[idx] if 0 <= idx < len(options) else None
        if correct_text is None:
            return False
        a = ans.upper()
        if a == correct_letter:
            return True
        aidx = LETTERS.find(a)
        ans_text = options[aidx] if 0 <= aidx < len(options) else ans
        # 允许直接输入选项内容作答
        return _norm_loose(ans_text) == _norm_loose(correct_text)
    if qtype == 'multi_choice':
        # 答案形如 "ABC"；必须完全一致（不多选、不漏选）
        expected = set(str(question['answer']).strip().upper())
        got = {c for c in ans.upper() if c in LETTERS}
        return bool(got) and got == expected
    if qtype in ('cloze', 'short_answer'):
        accepted = str(question['answer']).split('|')
        if qtype == 'cloze':
            return any(_norm_loose(ans) == _norm_loose(t) for t in accepted)
        return any(_norm_loose(t) in _norm_loose(ans) or _norm_loose(ans) in _norm_loose(t) for t in accepted)
    if qtype == 'self_rate':
        return ans.lower() in ('good', 'easy')
    raise ValueError(f'未知题型: {qtype}')


def _stable_shuffle(items, seed: str):
    return sorted(items, key=lambda x: sha256(f'{seed}:{x}'.encode('utf-8')).hexdigest())


def create_session(db, pack_id: str, *, module_ids=None, count: int = 10,
                   mode: str = 'practice', seed: str | None = None) -> dict:
    """创建练习/复习会话。practice 优先未作答题；review 取到期卡片。"""
    if mode not in ('practice', 'review'):
        raise ValueError('mode 必须是 practice 或 review')
    pack = db.execute('SELECT id FROM packs WHERE id=?', (pack_id,)).fetchone()
    if pack is None:
        raise LookupError(f'内容包不存在: {pack_id}')

    if mode == 'review':
        from .review import due_reviews
        due = due_reviews(db, pack_id=pack_id, limit=max(count, 50))
        candidates = [r['id'] for r in due]
    else:
        module_filter = ''
        params: list = [pack_id]
        if module_ids:
            module_filter = 'AND q.module_id IN (%s)' % ','.join('?' * len(module_ids))
            params.extend(module_ids)
        rows = db.execute(
            f'''SELECT q.id, (SELECT COUNT(*) FROM attempts a
                  WHERE a.question_id=q.id AND a.valid_for_stats=1) AS attempt_count
               FROM questions q WHERE q.pack_id=? {module_filter}''',
            params,
        ).fetchall()
        # 优先从未见过的题开始，其余按稳定随机
        unseen = [r['id'] for r in rows if r['attempt_count'] == 0]
        seen = [r['id'] for r in rows if r['attempt_count'] > 0]
        seed = seed or uuid4().hex
        candidates = _stable_shuffle(unseen, seed) + _stable_shuffle(seen, seed)

    selected = candidates[: max(1, min(count, 100))]
    if not selected:
        raise ValueError('没有可用的题目（复习模式请先产生作答记录）')

    session_id = uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        'INSERT INTO quiz_sessions (id,pack_id,mode,status,meta_json,created_at) VALUES (?,?,?,?,?,?)',
        (session_id, pack_id, mode, 'active',
         json.dumps({'requested_count': count, 'module_ids': module_ids or [], 'seed': seed or ''}, ensure_ascii=False),
         now),
    )
    for ord_no, qid in enumerate(selected):
        db.execute('INSERT INTO session_questions (session_id,question_id,ord) VALUES (?,?,?)',
                   (session_id, qid, ord_no))
    return {'session_id': session_id, 'mode': mode, 'count': len(selected), 'pack_id': pack_id}


def session_detail(db, session_id: str, *, reveal: bool = False) -> dict:
    session = db.execute('SELECT * FROM quiz_sessions WHERE id=?', (session_id,)).fetchone()
    if session is None:
        raise LookupError(f'会话不存在: {session_id}')
    rows = db.execute(
        '''SELECT q.*, sq.ord,
                  (SELECT a.id FROM attempts a WHERE a.question_id=q.id AND a.session_id=sq.session_id
                   ORDER BY a.id DESC LIMIT 1) AS last_attempt_id
           FROM session_questions sq JOIN questions q ON q.id=sq.question_id
           WHERE sq.session_id=? ORDER BY sq.ord''',
        (session_id,),
    ).fetchall()
    questions = []
    for r in rows:
        item = {
            'id': r['id'], 'ord': r['ord'], 'module_id': r['module_id'], 'type': r['type'],
            'stem': r['stem'], 'options': json.loads(r['options_json'] or '[]'),
            'difficulty': r['difficulty'], 'estimated_seconds': r['estimated_seconds'],
            'image_path': r['image_path'], 'tags': json.loads(r['tags_json'] or '[]'),
            'answered': r['last_attempt_id'] is not None,
        }
        if reveal:
            item['answer'] = r['answer']
            item['explanation'] = r['explanation']
        questions.append(item)
    return {
        'session_id': session['id'], 'pack_id': session['pack_id'], 'mode': session['mode'],
        'status': session['status'], 'created_at': session['created_at'], 'questions': questions,
    }


def submit_answer(db, session_id: str, question_id: str, *, answer, confidence=None,
                  hint_level: int = 0, elapsed_ms: int = 0) -> dict:
    """提交一题作答：判分 → 落库 → 重建该题所属内容包的复习与掌握度投影。"""
    from .mastery import rebuild_mastery
    from .review import rebuild_reviews

    session = db.execute('SELECT * FROM quiz_sessions WHERE id=?', (session_id,)).fetchone()
    if session is None:
        raise LookupError(f'会话不存在: {session_id}')
    if session['status'] != 'active':
        raise ValueError('会话已结束')
    linked = db.execute('SELECT 1 FROM session_questions WHERE session_id=? AND question_id=?',
                        (session_id, question_id)).fetchone()
    if linked is None:
        raise ValueError('该题不属于此会话')
    question = db.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
    if question is None:
        raise LookupError(f'题目不存在: {question_id}')

    correct = int(grade(question, answer))
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        '''INSERT INTO attempts (question_id,session_id,answer,correct,confidence,hint_level,
                                 elapsed_ms,valid_for_stats,raw_json,submitted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (question_id, session_id, None if answer is None else str(answer), correct,
         float(confidence) if confidence is not None else None, int(hint_level),
         int(elapsed_ms), 1,
         json.dumps({'session_mode': session['mode']}, ensure_ascii=False), now),
    )
    rebuild_reviews(db, pack_id=session['pack_id'])
    rebuild_mastery(db, pack_id=session['pack_id'])

    remaining = db.execute(
        '''SELECT COUNT(*) FROM session_questions sq
           WHERE sq.session_id=? AND sq.question_id NOT IN
             (SELECT question_id FROM attempts WHERE session_id=?)''',
        (session_id, session_id),
    ).fetchone()[0]
    if remaining == 0:
        db.execute("UPDATE quiz_sessions SET status='finished', finished_at=? WHERE id=?", (now, session_id))
    return {
        'question_id': question_id,
        'correct': bool(correct),
        'answer': question['answer'],
        'explanation': question['explanation'],
        'remaining': remaining,
        'session_finished': remaining == 0,
    }


def session_result(db, session_id: str) -> dict:
    detail_rows = db.execute(
        '''SELECT q.id, q.module_id, a.correct FROM session_questions sq
           JOIN questions q ON q.id=sq.question_id
           JOIN attempts a ON a.question_id=q.id AND a.session_id=sq.session_id
           WHERE sq.session_id=?''',
        (session_id,),
    ).fetchall()
    total = len(detail_rows)
    correct = sum(1 for r in detail_rows if r['correct'])
    by_module = {}
    for r in detail_rows:
        m = by_module.setdefault(r['module_id'], {'total': 0, 'correct': 0})
        m['total'] += 1
        m['correct'] += int(bool(r['correct']))
    return {
        'session_id': session_id, 'total': total, 'correct': correct,
        'accuracy': correct / total if total else 0,
        'by_module': by_module,
    }
