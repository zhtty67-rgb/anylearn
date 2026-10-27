"""项目层：门禁、验收、产物检查、与能力等级的联动。

设计原则：
1. **验收对象是产物，不是答案。** 交付物有明确的判定方式（文件/测试/运行/数据/解释）。
2. **项目验收通过才解锁 L4/L5。** 做题做得好只能到 L3，这是项目层的存在意义。
3. **用户自己的真实项目是一等公民。** authored_by='user' 的项目同样走这套验收。
4. **失败也是证据。** 每次提交都落库，失败计入概念证据而不推进等级。

安全边界：`test` / `run` 两类交付物会执行命令。命令来自内容包，属于**可信输入**；
用户自建项目的命令由用户自己写，等同于用户在本机执行，与插件运行权限一致。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TIMEOUT = 60
MAX_CAPTURE = 4000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ 门禁
def project_gate(db, project_id: str) -> dict:
    """检查项目能否开始：所需单元是否都已达标。"""
    row = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
    if row is None:
        raise KeyError(f'项目不存在: {project_id}')
    missing = []
    for req in db.execute(
        '''SELECT pr.unit_id, pr.min_level, u.title FROM project_requirements pr
           JOIN course_units u ON u.id=pr.unit_id WHERE pr.project_id=?''', (project_id,)):
        met, detail = _unit_level_met(db, req['unit_id'], req['min_level'])
        if not met:
            missing.append({'unit_id': req['unit_id'], 'title': req['title'],
                            'min_level': req['min_level'], **detail})
    return {'project_id': project_id, 'open': not missing, 'missing': missing}


def _unit_level_met(db, unit_id: str, min_level: int) -> tuple[bool, dict]:
    """单元内所有 core 概念是否都达到 min_level。"""
    rows = db.execute(
        '''SELECT uc.concept_id, uc.target_level, c.name,
                  COALESCE(a.level,0) AS level
           FROM unit_concepts uc JOIN concepts c ON c.id=uc.concept_id
           LEFT JOIN concept_ability a ON a.concept_id=uc.concept_id
           WHERE uc.unit_id=? AND uc.role='core' ''', (unit_id,)).fetchall()
    if not rows:
        return True, {}
    need = max(min_level, max(r['target_level'] for r in rows))
    short = [{'concept': r['name'], 'level': r['level'], 'need': need}
             for r in rows if r['level'] < need]
    return (not short), {'required_level': need, 'short': short}


# ------------------------------------------------------------------ 产物检查
def _check_file(acc: dict, base: Path) -> dict:
    rel = acc.get('path')
    if not rel:
        return {'name': 'file', 'ok': False, 'detail': '缺少 path'}
    target = (base / rel).resolve()
    if not str(target).startswith(str(Path(base).resolve())):
        return {'name': 'file', 'ok': False, 'detail': '路径越界'}
    if not target.is_file():
        return {'name': 'file', 'ok': False, 'detail': f'文件不存在: {rel}'}
    size = target.stat().st_size
    min_bytes = int(acc.get('min_bytes', 1))
    return {'name': 'file', 'ok': size >= min_bytes, 'detail': f'{rel} ({size} 字节)',
            'observed': size, 'expected_min': min_bytes}


def _run_cmd(cmd: str, base: Path, timeout: int) -> dict:
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(base), capture_output=True,
                              text=True, timeout=timeout, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        return {'rc': None, 'stdout': '', 'stderr': f'超时 {timeout}s', 'timeout': True}
    return {'rc': proc.returncode, 'stdout': (proc.stdout or '')[-MAX_CAPTURE:],
            'stderr': (proc.stderr or '')[-MAX_CAPTURE:], 'timeout': False}


def _check_run(acc: dict, base: Path) -> dict:
    cmd = acc.get('cmd')
    if not cmd:
        return {'name': 'run', 'ok': False, 'detail': '缺少 cmd'}
    expect_exit = int(acc.get('expect_exit', 0))
    res = _run_cmd(cmd, base, int(acc.get('timeout', DEFAULT_TIMEOUT)))
    ok = (not res['timeout']) and res['rc'] == expect_exit
    detail = f'退出码 {res["rc"]}（期望 {expect_exit}）'
    needle = acc.get('expect_stdout_contains')
    if needle:
        found = needle in res['stdout']
        ok = ok and found
        detail += f'；输出{"包含" if found else "未包含"} {needle!r}'
    return {'name': 'run', 'ok': ok, 'detail': detail, 'cmd': cmd,
            'stdout_tail': res['stdout'][-800:], 'stderr_tail': res['stderr'][-800:]}


def _check_data(acc: dict, base: Path) -> dict:
    rel = acc.get('path')
    if not rel:
        return {'name': 'data', 'ok': False, 'detail': '缺少 path'}
    target = (base / rel).resolve()
    if not str(target).startswith(str(Path(base).resolve())) or not target.is_file():
        return {'name': 'data', 'ok': False, 'detail': f'文件不存在: {rel}'}
    try:
        doc = json.loads(target.read_text(encoding='utf-8'))
    except Exception as exc:
        return {'name': 'data', 'ok': False, 'detail': f'不是合法 JSON: {exc}'}
    path = acc.get('jsonpath', '$')
    node = doc
    for part in [p for p in path.lstrip('$').split('.') if p]:
        if not isinstance(node, dict) or part not in node:
            return {'name': 'data', 'ok': False, 'detail': f'路径不存在: {path}'}
        node = node[part]
    ok = True
    detail = f'{path} = {node!r}'
    if 'min' in acc:
        ok = ok and isinstance(node, (int, float)) and node >= acc['min']
        detail += f'（要求 >= {acc["min"]}）'
    if 'max' in acc:
        ok = ok and isinstance(node, (int, float)) and node <= acc['max']
        detail += f'（要求 <= {acc["max"]}）'
    if 'equals' in acc:
        ok = ok and node == acc['equals']
        detail += f'（要求 == {acc["equals"]!r}）'
    return {'name': 'data', 'ok': ok, 'detail': detail, 'observed': node}


def _check_explain(acc: dict, payload: dict) -> dict:
    """解释类交付物：框架只检查结构完整性；语义评审交给 AI 或人工。

    不在这里假装能自动判断一段解释对不对——那会变成模型随便给分。
    """
    rubric = acc.get('rubric') or []
    text = str(payload.get('explain') or payload.get('text') or '').strip()
    min_chars = int(acc.get('min_chars', 20))
    ok = len(text) >= min_chars
    return {'name': 'explain', 'ok': ok,
            'detail': f'{len(text)} 字符（要求 >= {min_chars}）；待评 ${len(rubric)} 项 rubric',
            'needs_review': True, 'rubric': rubric, 'text_len': len(text)}


def evaluate_deliverable(db, deliverable_id: str, *, artifact_base: Path,
                         payload: dict | None = None) -> dict:
    """按交付物的 acceptance 配置检查产物，返回逐项结果。不写库。"""
    d = db.execute('SELECT * FROM project_deliverables WHERE id=?', (deliverable_id,)).fetchone()
    if d is None:
        raise KeyError(f'交付物不存在: {deliverable_id}')
    base = Path(artifact_base)
    base.mkdir(parents=True, exist_ok=True)
    acc = json.loads(d['acceptance_json'] or '{}')
    payload = payload or {}

    if d['kind'] == 'file':
        checks = [_check_file(acc, base)]
    elif d['kind'] == 'test':
        cmd = acc.get('cmd') or f'{sys.executable} -m pytest -q'
        res = _run_cmd(cmd, base, int(acc.get('timeout', 120)))
        ok = (not res['timeout']) and res['rc'] == 0
        checks = [{'name': 'test', 'ok': ok, 'detail': f'退出码 {res["rc"]}', 'cmd': cmd,
                   'stdout_tail': res['stdout'][-1200:], 'stderr_tail': res['stderr'][-800:]}]
    elif d['kind'] == 'run':
        checks = [_check_run(acc, base)]
    elif d['kind'] == 'data':
        checks = [_check_data(acc, base)]
    elif d['kind'] == 'explain':
        checks = [_check_explain(acc, payload)]
    else:  # pragma: no cover - 由 CHECK 约束兜底
        raise ValueError(f'未知交付物类型: {d["kind"]}')

    ok = all(c['ok'] for c in checks)
    needs_review = any(c.get('needs_review') for c in checks)
    # 三态：结构没过 = fail；结构过了但语义待评审 = pending；全部机器可判且通过 = pass
    verdict = 'fail' if not ok else ('pending' if needs_review else 'pass')
    return {'deliverable_id': deliverable_id, 'title': d['title'], 'kind': d['kind'],
            'ok': ok, 'verdict': verdict, 'needs_review': needs_review, 'checks': checks}


# ------------------------------------------------------------------ 提交
def submit_deliverable(db, deliverable_id: str, *, artifact_base: Path,
                       payload: dict | None = None, assisted: bool = False) -> dict:
    """提交一次交付物：检查 → 落库 → 刷新里程碑/项目状态 → 联动能力等级。"""
    d = db.execute(
        '''SELECT pd.*, pm.project_id AS project_id
           FROM project_deliverables pd
           JOIN project_milestones pm ON pm.id=pd.milestone_id
           WHERE pd.id=?''', (deliverable_id,)).fetchone()
    if d is None:
        raise KeyError(f'交付物不存在: {deliverable_id}')
    result = evaluate_deliverable(db, deliverable_id, artifact_base=artifact_base,
                                  payload=payload)
    verdict = result['verdict']
    today = _now()
    payload = payload or {}
    db.execute(
        '''INSERT INTO deliverable_submissions
           (deliverable_id,project_id,milestone_id,artifact_path,payload_json,verdict,
            checks_json,assisted,submitted_at)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (deliverable_id, d['project_id'], d['milestone_id'],
         payload.get('path'),
         json.dumps(payload, ensure_ascii=False), verdict,
         json.dumps(result['checks'], ensure_ascii=False), int(bool(assisted)), today),
    )
    _refresh_progress(db, d['project_id'])
    _link_ability(db, d['project_id'])
    return {**result, 'verdict': verdict, 'milestone_id': d['milestone_id'],
            'project_id': d['project_id']}


def review_submission(db, submission_id: int, *, approved: bool, reviewer: str = 'human',
                      note: str = '') -> dict:
    """人工/AI 评审解释类交付物。这是 pending → pass/fail 的唯一出口。

    评审结论写入新的提交记录（保持历史不可变），而不是改写原记录。
    """
    sub = db.execute('SELECT * FROM deliverable_submissions WHERE id=?',
                     (submission_id,)).fetchone()
    if sub is None:
        raise KeyError(f'提交不存在: {submission_id}')
    if sub['verdict'] != 'pending':
        raise ValueError(f'只有 pending 的提交可以评审，当前是 {sub["verdict"]}')
    checks = json.loads(sub['checks_json'] or '[]')
    for c in checks:
        if c.get('needs_review'):
            c['reviewed_by'] = reviewer
            c['review_ok'] = bool(approved)
            if note:
                c['review_note'] = note
    verdict = 'pass' if approved else 'fail'
    db.execute(
        '''INSERT INTO deliverable_submissions
           (deliverable_id,project_id,milestone_id,artifact_path,payload_json,verdict,
            checks_json,assisted,submitted_at)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (sub['deliverable_id'], sub['project_id'], sub['milestone_id'], sub['artifact_path'],
         sub['payload_json'], verdict, json.dumps(checks, ensure_ascii=False),
         sub['assisted'], _now()),
    )
    _refresh_progress(db, sub['project_id'])
    _link_ability(db, sub['project_id'])
    return {'submission_id': submission_id, 'verdict': verdict, 'reviewer': reviewer}


def pending_submissions(db, *, pack_id: str | None = None) -> list[dict]:
    sql = ("SELECT s.*, d.title FROM deliverable_submissions s "
           "JOIN project_deliverables d ON d.id=s.deliverable_id "
           "WHERE s.verdict='pending'")
    args: tuple = ()
    if pack_id:
        sql += " AND s.project_id LIKE ?"
        args = (f'{pack_id}:%',)
    sql += ' ORDER BY s.id DESC'
    return [dict(r) for r in db.execute(sql, args)]


def _milestone_passed(db, milestone_id: str) -> bool:
    """该里程碑的必需交付物是否每个都至少通过过一次。"""
    for d in db.execute('SELECT id FROM project_deliverables '
                        'WHERE milestone_id=? AND required=1', (milestone_id,)):
        if db.execute("SELECT 1 FROM deliverable_submissions WHERE deliverable_id=? AND verdict='pass' LIMIT 1",
                      (d['id'],)).fetchone() is None:
            return False
    # 有未评审的必需交付物时，里程碑不能算通过
    for d in db.execute('SELECT id FROM project_deliverables '
                        'WHERE milestone_id=? AND required=1', (milestone_id,)):
        if db.execute("SELECT 1 FROM deliverable_submissions WHERE deliverable_id=? AND verdict='pending' LIMIT 1",
                      (d['id'],)).fetchone() is not None:
            if db.execute("SELECT 1 FROM deliverable_submissions WHERE deliverable_id=? AND verdict='pass' LIMIT 1",
                          (d['id'],)).fetchone() is None:
                return False
    return True


def _refresh_progress(db, project_id: str) -> None:
    now = _now()
    for m in db.execute('SELECT id FROM project_milestones WHERE project_id=?', (project_id,)):
        passed = _milestone_passed(db, m['id'])
        has_sub = db.execute('SELECT 1 FROM deliverable_submissions WHERE milestone_id=? LIMIT 1',
                             (m['id'],)).fetchone() is not None
        status = 'passed' if passed else ('in_progress' if has_sub else 'ready')
        db.execute(
            '''INSERT INTO milestone_progress (milestone_id,status,passed_at,updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(milestone_id) DO UPDATE SET status=excluded.status,
                 passed_at=COALESCE(milestone_progress.passed_at, excluded.passed_at),
                 updated_at=excluded.updated_at''',
            (m['id'], status, now if passed else None, now),
        )
    gate = project_gate(db, project_id)
    ms = db.execute('SELECT id FROM project_milestones WHERE project_id=?', (project_id,)).fetchall()
    all_passed = bool(ms) and all(_milestone_passed(db, m['id']) for m in ms)
    has_pending = db.execute(
        "SELECT 1 FROM deliverable_submissions WHERE project_id=? AND verdict='pending' LIMIT 1",
        (project_id,)).fetchone() is not None
    status = ('completed' if all_passed else
              ('in_review' if has_pending else
               ('in_progress' if gate['open'] else 'locked')))
    db.execute(
        '''INSERT INTO project_progress (project_id,status,started_at,completed_at,updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(project_id) DO UPDATE SET status=excluded.status,
             started_at=COALESCE(project_progress.started_at, excluded.started_at),
             completed_at=COALESCE(excluded.completed_at, project_progress.completed_at),
             updated_at=excluded.updated_at''',
        (project_id, status, now if gate['open'] else None, now if all_passed else None, now),
    )


def _link_ability(db, project_id: str) -> None:
    """项目验收通过 → 给相关概念补上「非辅助的验收类证据」。

    只补 verify_pass（未 assisted）；失败的提交记为 verify_fail。
    这样做题最多到 L3，L4/L5 必须靠真实产物验收。
    """
    from . import lesson
    pack = db.execute('SELECT pack_id FROM projects WHERE id=?', (project_id,)).fetchone()
    if pack is None:
        return
    concept_rows = db.execute('SELECT concept_id FROM project_concepts WHERE project_id=?',
                              (project_id,)).fetchall()
    if not concept_rows:
        return
    for sub in db.execute(
            'SELECT * FROM deliverable_submissions WHERE project_id=? ORDER BY id', (project_id,)):
        passed_ms = _milestone_passed(db, sub['milestone_id'])
        if sub['verdict'] == 'pending':
            continue  # 待评审不算证据，也不计失败
        for c in concept_rows:
            _link_one(db, pack['pack_id'], sub, c['concept_id'], passed_ms)
    lesson.rebuild_ability(db, pack['pack_id'])


def _link_one(db, pack_id: str, sub, concept_id: str, passed_ms: bool) -> None:
    """把一次提交转成该概念的证据。辅助通过也要记账，只是不计入独立证据。"""
    from . import lesson
    if sub['verdict'] == 'pending':
        return  # 待评审：不算证据，也不算失败
    if sub['verdict'] == 'fail':
        kind, assisted = 'project_fail', False
    elif passed_ms:
        # 验收通过。辅助通过记成「辅助型 attempt」，仍留在证据里但不推进等级
        kind, assisted = ('project_pass', False) if not sub['assisted'] else ('attempt', True)
    else:
        return
    lesson.record_event(db, pack_id, kind, concept_id=concept_id,
                        assisted=assisted, occurred_at=sub['submitted_at'],
                        payload={'source': 'project', 'deliverable': sub['deliverable_id'],
                                 'verdict': sub['verdict']})


# ------------------------------------------------------------------ 查询
def project_status(db, project_id: str) -> dict:
    p = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
    if p is None:
        raise KeyError(f'项目不存在: {project_id}')
    gate = project_gate(db, project_id)
    milestones = []
    for m in db.execute('SELECT * FROM project_milestones WHERE project_id=? ORDER BY sort_no, code',
                        (project_id,)):
        items = []
        for d in db.execute('SELECT * FROM project_deliverables WHERE milestone_id=? ORDER BY sort_no, code',
                            (m['id'],)):
            last = db.execute(
                '''SELECT verdict, submitted_at FROM deliverable_submissions
                   WHERE deliverable_id=? ORDER BY id DESC LIMIT 1''', (d['id'],)).fetchone()
            items.append({'deliverable_id': d['id'], 'title': d['title'], 'kind': d['kind'],
                          'required': bool(d['required']),
                          'last_verdict': last['verdict'] if last else None,
                          'last_at': last['submitted_at'] if last else None})
        passed = _milestone_passed(db, m['id'])
        milestones.append({'milestone_id': m['id'], 'title': m['title'],
                           'objective': m['objective'], 'est_minutes': m['est_minutes'],
                           'passed': passed, 'deliverables': items})
    prog = db.execute('SELECT * FROM project_progress WHERE project_id=?', (project_id,)).fetchone()
    return {'project_id': project_id, 'title': p['title'], 'brief': p['brief'],
            'goal': p['goal'], 'authored_by': p['authored_by'],
            'status': prog['status'] if prog else ('available' if gate['open'] else 'locked'),
            'gate': gate,
            'milestones': milestones,
            'completed': all(m['passed'] for m in milestones) if milestones else False}


def user_project(db, pack_id: str, *, code: str, title: str, brief: str, goal: str,
                 repo_path: str | None = None) -> dict:
    """登记学习者自己的真实项目。走同一套验收，但不需要内容包声明。"""
    pid = f'{pack_id}:{code}'
    db.execute(
        '''INSERT INTO projects (id,pack_id,code,title,brief,goal,authored_by,repo_path,created_at)
           VALUES (?,?,?,?,?,?,'user',?,?)
           ON CONFLICT(id) DO UPDATE SET title=excluded.title, brief=excluded.brief,
             goal=excluded.goal, repo_path=excluded.repo_path''',
        (pid, pack_id, code, title, brief, goal, repo_path, _now()),
    )
    return {'project_id': pid, 'status': 'created'}
