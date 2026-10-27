"""确定性、可重放的掌握度投影，仅由作答记录推导。

移植自 gongkao-learning-os：拉普拉斯平滑 (1+正证据)/(2+正+负证据)，
提示成功打折，按 pack 范围重建。
"""
from datetime import datetime, timezone

HINT_SUCCESS_MULTIPLIERS = {
    0: 1.0,   # 独立做对
    1: 0.65,  # 一级提示后做对
    2: 0.45,  # 二级提示后做对
    3: 0.25,  # 三级提示后做对
    4: 0.0,   # 完整解析后做对，不积累正面证据
}


def rebuild_mastery(db, pack_id: str | None = None):
    """重建（单个内容包的）全部掌握度投影。作答记录是唯一事实源。"""
    timestamp = datetime.now(timezone.utc).isoformat()
    pack_filter = 'AND q.pack_id=?' if pack_id else ()
    rows = db.execute(
        f'''SELECT a.id AS attempt_id, a.correct, a.elapsed_ms, a.hint_level, a.submitted_at,
                   q.estimated_seconds, qkm.node_id AS knowledge_node_id, qkm.weight
            FROM attempts a
            JOIN questions q ON q.id=a.question_id
            JOIN question_node_map qkm ON qkm.question_id=a.question_id
            WHERE a.submitted_at IS NOT NULL AND a.valid_for_stats=1 {pack_filter}
            ORDER BY a.submitted_at, a.id, qkm.node_id''',
        ((pack_id,) if pack_id else ()),
    ).fetchall()
    if pack_id:
        db.execute(
            'DELETE FROM mastery_evidence WHERE knowledge_node_id IN '
            '(SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
        db.execute(
            'DELETE FROM mastery_state WHERE knowledge_node_id IN '
            '(SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
        node_rows = db.execute('SELECT id FROM knowledge_nodes WHERE pack_id=?', (pack_id,)).fetchall()
    else:
        db.execute('DELETE FROM mastery_evidence')
        db.execute('DELETE FROM mastery_state')
        node_rows = db.execute('SELECT id FROM knowledge_nodes').fetchall()

    db.executemany(
        '''INSERT INTO mastery_evidence
           (attempt_id,knowledge_node_id,success_evidence,failure_evidence,time_ratio,timed,created_at)
           VALUES (?,?,?,?,?,?,?)''',
        [(
            row['attempt_id'], row['knowledge_node_id'],
            (row['weight'] * HINT_SUCCESS_MULTIPLIERS.get(row['hint_level'], 1.0)) if row['correct'] else 0,
            0 if row['correct'] else row['weight'],
            row['elapsed_ms'] / (row['estimated_seconds'] * 1000) if row['estimated_seconds'] else 0,
            int(bool(row['estimated_seconds']) and row['elapsed_ms'] <= row['estimated_seconds'] * 1000),
            row['submitted_at'],
        ) for row in rows],
    )
    for node in node_rows:
        evidence = db.execute(
            '''SELECT me.*, a.correct, a.hint_level FROM mastery_evidence me
               JOIN attempts a ON a.id=me.attempt_id
               WHERE me.knowledge_node_id=? ORDER BY a.submitted_at DESC, a.id DESC''',
            (node['id'],),
        ).fetchall()
        positive = sum(r['success_evidence'] for r in evidence)
        negative = sum(r['failure_evidence'] for r in evidence)
        count = len(evidence)
        recent = evidence[:20]
        timed = [r for r in evidence if r['timed']]
        db.execute(
            '''INSERT INTO mastery_state
               (knowledge_node_id,mastery_score,positive_evidence,negative_evidence,evidence_count,
                recent_accuracy,timed_accuracy,mean_time_ratio,hint_dependency,last_attempt_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (
                node['id'], (1 + positive) / (2 + positive + negative), positive, negative, count,
                sum(r['correct'] for r in recent) / len(recent) if recent else None,
                sum(r['correct'] for r in timed) / len(timed) if timed else None,
                sum(r['time_ratio'] for r in timed) / len(timed) if timed else None,
                sum(r['hint_level'] > 0 for r in evidence) / count if count else 0,
                evidence[0]['created_at'] if evidence else None, timestamp,
            ),
        )


def overall_mastery(db, pack_id: str) -> float:
    row = db.execute(
        '''SELECT SUM(ms.mastery_score * kn.weight) weighted, SUM(kn.weight) total
           FROM mastery_state ms JOIN knowledge_nodes kn ON kn.id=ms.knowledge_node_id
           WHERE kn.pack_id=?''',
        (pack_id,),
    ).fetchone()
    return row['weighted'] / row['total'] if row and row['total'] else 0.5
