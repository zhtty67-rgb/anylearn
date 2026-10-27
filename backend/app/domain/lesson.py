"""学习框架：课程推进 / 能力定级 / 卡点诊断。

设计原则（与任何learn 的掌握度、复习一致）：
1. **等级由证据推导，不由模型打分。** 模型可以生成讲解与追问，但不能直接写 level。
2. **独立与辅助分开记。** 用了提示、看了讲解再答对，算「辅助通过」，不推进等级。
3. **全部可重放。** concept_ability 是 learning_events + attempts 的投影，随时可重建。
4. **框架不含学科内容。** 教什么由内容包注入。

等级语义（L1..L5）：
    L1 识别  —— 见过、能辨认（有独立的答对记录）
    L2 解释  —— 能用自己的话说清（通过 self_explain 步骤）
    L3 应用  —— 能在有限提示下完成任务（独立完成 practice）
    L4 诊断  —— 能定位问题、比较方案（独立 + 无误解命中 + 多次证据）
    L5 迁移  —— 在陌生场景仍成立（独立通过 verify 验收）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

LEVEL_NAMES = {0: '未接触', 1: '识别', 2: '解释', 3: '应用', 4: '诊断', 5: '迁移'}

# 达到某等级所需的最小独立证据数（防止一次蒙对就跳级）
MIN_INDEPENDENT_FOR = {1: 1, 2: 1, 3: 2, 4: 3, 5: 4}

STEP_SEQUENCE = ('diagnose', 'explain', 'socratic', 'feynman', 'practice', 'verify', 'review')

# 可作为学习证据的事件类型（与迁移 003 的 CHECK 约束一致）
EVENT_KINDS = frozenset({
    'step_viewed', 'hint_used', 'self_explain', 'attempt',
    'verify_pass', 'verify_fail', 'misconception_hit',
    'project_pass', 'project_fail',
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ 事件
def record_event(db, pack_id: str, kind: str, *, unit_id=None, step_id=None,
                 concept_id=None, session_id=None, hint_level=0, assisted=None,
                 payload=None, occurred_at=None) -> int:
    """写入一条学习事件。assisted 缺省时按 hint_level>0 推断。"""
    if assisted is None:
        assisted = 1 if (hint_level or 0) > 0 else 0
    cur = db.execute(
        '''INSERT INTO learning_events
           (pack_id,session_id,unit_id,step_id,concept_id,kind,hint_level,assisted,payload_json,occurred_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (pack_id, session_id, unit_id, step_id, concept_id, kind, int(hint_level or 0),
         int(bool(assisted)), json.dumps(payload or {}, ensure_ascii=False),
         occurred_at or _now()),
    )
    return int(cur.lastrowid)


# ------------------------------------------------------------------ 定级
def rebuild_ability(db, pack_id: str | None = None) -> int:
    """由 learning_events 重放，重建 concept_ability。返回更新的概念数。

    规则（全部可追溯到具体事件）：
    - 独立通过（nonzero evidence）计数 → 决定 best_independent_level
    - verify_pass 且非 assisted → 额外解锁 L5
    - misconception_hit 会压低天花板（L4 需要 0 次误解命中）
    """
    if pack_id:
        concept_ids = [r[0] for r in db.execute(
            '''SELECT DISTINCT concept_id FROM learning_events
               WHERE pack_id=? AND concept_id IS NOT NULL''', (pack_id,))]
        db.execute('DELETE FROM concept_ability WHERE concept_id IN '
                   '(SELECT id FROM concepts WHERE pack_id=?)', (pack_id,))
    else:
        concept_ids = [r[0] for r in db.execute(
            'SELECT DISTINCT concept_id FROM learning_events WHERE concept_id IS NOT NULL')]
        db.execute('DELETE FROM concept_ability')

    updated = 0
    for cid in concept_ids:
        rows = db.execute(
            '''SELECT kind, assisted, hint_level, occurred_at FROM learning_events
               WHERE concept_id=? ORDER BY occurred_at, id''', (cid,)).fetchall()
        _ensure_ability_row(db, cid)
        independent = assisted_passes = failures = mis = 0
        self_explained = verify_independent = False
        last_at = None
        for r in rows:
            last_at = r['occurred_at']
            k = r['kind']
            if k in ('attempt', 'verify_pass', 'project_pass'):
                if r['assisted']:
                    assisted_passes += 1
                else:
                    independent += 1
                    if k in ('verify_pass', 'project_pass'):
                        verify_independent = True
            elif k in ('verify_fail', 'project_fail'):
                failures += 1
            elif k == 'misconception_hit':
                mis += 1
            elif k == 'self_explain':
                # 自述讲解只有在「非辅助」时才算解释证据
                if not r['assisted']:
                    self_explained = True

        level = 0
        if independent >= MIN_INDEPENDENT_FOR[1]:
            level = 1
        if level == 1 and self_explained:
            level = 2
        if level == 2 and independent >= MIN_INDEPENDENT_FOR[3]:
            level = 3
        if level == 3 and independent >= MIN_INDEPENDENT_FOR[4] and mis == 0:
            level = 4
        if level == 4 and verify_independent and independent >= MIN_INDEPENDENT_FOR[5]:
            level = 5

        db.execute(
            '''INSERT INTO concept_ability
               (concept_id,level,best_independent_level,independent_passes,assisted_passes,
                failures,misconception_hits,last_evidence_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(concept_id) DO UPDATE SET level=excluded.level,
                 best_independent_level=excluded.best_independent_level,
                 independent_passes=excluded.independent_passes,
                 assisted_passes=excluded.assisted_passes, failures=excluded.failures,
                 misconception_hits=excluded.misconception_hits,
                 last_evidence_at=excluded.last_evidence_at, updated_at=excluded.updated_at''',
            (cid, level, level, independent, assisted_passes, failures, mis, last_at, _now()),
        )
        updated += 1
    return updated


ACCESS_KINDS = ('attempt', 'verify_pass', 'project_pass')


def _ensure_ability_row(db, concept_id: str) -> None:
    """概念被事实源触碰过就该有投影行，哪怕等级还是 0。

    否则「只在提示后做对」这种最典型的卡点会因为没有行而看不到。
    """
    db.execute(
        '''INSERT INTO concept_ability
           (concept_id,level,best_independent_level,independent_passes,assisted_passes,
            failures,misconception_hits,last_evidence_at,updated_at)
           VALUES (?,0,0,0,0,0,0,NULL,?)
           ON CONFLICT(concept_id) DO NOTHING''', (concept_id, _now()))


def touch_concept(db, concept_id: str) -> None:
    """记录一次概念被触碰（无论等级是否变化），保证卡点诊断有据可查。"""
    _ensure_ability_row(db, concept_id)


# ------------------------------------------------------------------ 卡点诊断
def diagnose_blocker(db, concept_id: str, *, required_level: int | None = None) -> dict:
    """回答「为什么卡住」，返回可解释的依据，而不是一个百分比。

    检查顺序：
    1. 先修缺失 —— 前置概念等级低于本概念目标所需
    2. 误解命中 —— 命中过预设误解
    3. 仅辅助通过 —— 离开提示就做不对
    4. 证据不足 —— 根本没练过

    required_level：先修需要达到的等级。缺省时取本概念所属单元的核心目标等级；
    都没有则取 2（能解释）。「达标」的判定必须显式，不能隐含在代码里。
    """
    concept = db.execute('SELECT * FROM concepts WHERE id=?', (concept_id,)).fetchone()
    if concept is None:
        raise KeyError(f'概念不存在: {concept_id}')
    ability = db.execute('SELECT * FROM concept_ability WHERE concept_id=?', (concept_id,)).fetchone()
    level = ability['level'] if ability else 0

    if required_level is None:
        row = db.execute(
            '''SELECT MAX(uc.target_level) AS t FROM unit_concepts uc
               WHERE uc.concept_id=? AND uc.role='core' ''', (concept_id,)).fetchone()
        required_level = int(row['t']) if row and row['t'] else 2

    prereqs = db.execute(
        '''SELECT p.prerequisite_id, c.name, c.summary, COALESCE(a.level,0) AS level
           FROM concept_prerequisites p JOIN concepts c ON c.id=p.prerequisite_id
           LEFT JOIN concept_ability a ON a.concept_id=p.prerequisite_id
           WHERE p.concept_id=?''', (concept_id,)).fetchall()
    weak = [dict(r) for r in prereqs if r['level'] < required_level]

    reasons = []
    if weak:
        names = '、'.join(f'{w["name"]}(L{w["level"]})' for w in weak)
        reasons.append({'code': 'prerequisite_gap',
                        'detail': f'前置概念未达到 L{required_level}：{names}',
                        'required_level': required_level,
                        'prerequisites': weak})
    if ability and ability['misconception_hits'] > 0:
        reasons.append({'code': 'misconception',
                        'detail': f'命中既定误解 {ability["misconception_hits"]} 次'})
    if ability and ability['independent_passes'] == 0 and ability['assisted_passes'] > 0:
        reasons.append({'code': 'hint_dependency', 'detail': '只在提示后做对过，尚无独立完成记录'})
    if level == 0 and not reasons:
        reasons.append({'code': 'no_evidence', 'detail': '尚无学习记录'})

    return {
        'concept_id': concept_id,
        'concept': concept['name'],
        'level': level,
        'level_name': LEVEL_NAMES[level],
        'blocked': bool(reasons),
        'reasons': reasons,
        'next_action': _next_action(reasons, level),
    }


def _next_action(reasons, level) -> str:
    codes = {r['code'] for r in reasons}
    if 'misconception' in codes:
        return '针对误解做一次苏格拉底追问，再重试'
    if 'prerequisite_gap' in codes:
        return '先补先修概念，再回到本概念'
    if 'hint_dependency' in codes:
        return '撤掉提示，重做一次同类型任务'
    if 'no_evidence' in codes:
        return '从本概念的诊断题开始'
    if level < 5:
        return f'继续到 L{level + 1}（{LEVEL_NAMES[level + 1]}）的证据'
    return '已达最高级，安排延迟复习'


# ------------------------------------------------------------------ 单元推进
def _unit_concepts(db, unit_id):
    return db.execute(
        '''SELECT uc.concept_id, uc.target_level, c.name FROM unit_concepts uc
           JOIN concepts c ON c.id=uc.concept_id WHERE uc.unit_id=?
           ORDER BY uc.role, c.code''', (unit_id,)).fetchall()


def unit_status(db, unit_id: str) -> dict:
    """计算单元状态：步骤进度 + 每个概念的达标情况。"""
    unit = db.execute('SELECT * FROM course_units WHERE id=?', (unit_id,)).fetchone()
    if unit is None:
        raise KeyError(f'单元不存在: {unit_id}')
    steps = db.execute('SELECT * FROM unit_steps WHERE unit_id=? ORDER BY ord', (unit_id,)).fetchall()
    done_steps = {r['step_id'] for r in db.execute(
        'SELECT DISTINCT step_id FROM learning_events WHERE unit_id=? AND kind=?',
        (unit_id, 'step_viewed'))}
    concepts = []
    all_met = True
    for c in _unit_concepts(db, unit_id):
        ab = db.execute('SELECT level FROM concept_ability WHERE concept_id=?',
                        (c['concept_id'],)).fetchone()
        level = ab['level'] if ab else 0
        met = level >= c['target_level']
        all_met = all_met and met
        concepts.append({'concept_id': c['concept_id'], 'name': c['name'],
                         'level': level, 'target': c['target_level'], 'met': met})
    next_step = next((s for s in steps if s['id'] not in done_steps), None)
    return {
        'unit_id': unit_id,
        'title': unit['title'],
        'objective': unit['objective'],
        'steps_total': len(steps),
        'steps_done': len([s for s in steps if s['id'] in done_steps]),
        'next_step': dict(next_step) if next_step else None,
        'concepts': concepts,
        'all_targets_met': bool(concepts) and all_met,
    }


def advance_unit(db, unit_id: str, step_id: str, *, pack_id: str) -> dict:
    """标记一个步骤已完成，返回推进后的单元状态。"""
    step = db.execute('SELECT * FROM unit_steps WHERE id=? AND unit_id=?',
                      (step_id, unit_id)).fetchone()
    if step is None:
        raise KeyError(f'步骤 {step_id} 不属于单元 {unit_id}')
    already = db.execute(
        'SELECT 1 FROM learning_events WHERE step_id=? AND kind=?', (step_id, 'step_viewed')
    ).fetchone()
    if already is None:
        record_event(db, pack_id, 'step_viewed', unit_id=unit_id, step_id=step_id,
                     concept_id=step['concept_id'])
    rebuild_ability(db, pack_id)
    status = unit_status(db, unit_id)

    db.execute(
        '''INSERT INTO unit_progress (unit_id,status,current_step,started_at,updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(unit_id) DO UPDATE SET status=excluded.status,
             current_step=excluded.current_step, updated_at=excluded.updated_at''',
        (unit_id,
         'completed' if status['all_targets_met'] and status['next_step'] is None else 'in_progress',
         status['steps_done'], _now(), _now()),
    )
    return status


def next_unit(db, course_id: str) -> dict | None:
    """返回当前应当学的单元：第一个未完成且概念未全部达标者。"""
    for unit in db.execute('SELECT id FROM course_units WHERE course_id=? ORDER BY sort_no, code',
                           (course_id,)):
        status = unit_status(db, unit['id'])
        if not (status['all_targets_met'] and status['next_step'] is None):
            return status
    return None
