"""全部 REST 路由。任何端点都不含领域语义，模块/学科信息一律来自内容包。"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..ai.teacher import conversation_history, teacher_reply
from ..contentpack.loader import PackValidationError, discover_packs, install_all, install_pack, pack_state
from ..db import connect
from ..domain.analytics import overview
from ..domain import lesson
from ..domain import project as project_mod
from ..domain.quiz import create_session, session_detail, session_result, submit_answer
from ..domain.review import due_reviews
from ..importers.anki_apkg import import_apkg
from ..importers.jsonl_import import import_jsonl

router = APIRouter(prefix='/api')


def get_db(request: Request):
    return connect(request.app.state.db_path)


def get_pack_root(request: Request) -> Path:
    return Path(request.app.state.content_root)


# ---------- 内容包 ----------

@router.get('/packs')
def list_packs(request: Request):
    with get_db(request) as db:
        packs = []
        for row in db.execute('SELECT * FROM packs ORDER BY installed_at'):
            manifest = json.loads(row['manifest_json'])
            qcount = db.execute('SELECT COUNT(*) c FROM questions WHERE pack_id=?', (row['id'],)).fetchone()['c']
            ncount = db.execute('SELECT COUNT(*) c FROM knowledge_nodes WHERE pack_id=?', (row['id'],)).fetchone()['c']
            packs.append({
                'id': row['id'], 'name': row['name'], 'version': row['version'],
                'description': row['description'], 'questions': qcount, 'nodes': ncount,
                'modules': manifest.get('modules') or [],
                'theme': manifest.get('theme') or {},
                'ai': manifest.get('ai') or {},
                'source': manifest.get('source') or {},
                'installed_at': row['installed_at'], 'updated_at': row['updated_at'],
            })
        available = [
            {'pack_id': p.name, 'installed': pack_state(db, p.name) is not None}
            for p in discover_packs(get_pack_root(request))
        ]
    return {'packs': packs, 'available_in_root': available}


class InstallBody(BaseModel):
    pack_id: str | None = Field(default=None, description='内容包目录名；缺省扫描全部')


@router.post('/packs/install')
def install_packs(body: InstallBody, request: Request):
    root = get_pack_root(request)
    with get_db(request) as db:
        if body.pack_id:
            target = root / body.pack_id
            if not (target / 'pack.yaml').is_file():
                raise HTTPException(404, f'内容包目录不存在: {target}')
            try:
                return {'results': [install_pack(db, target, force=True)]}
            except PackValidationError as exc:
                raise HTTPException(422, str(exc))
        try:
            return {'results': install_all(db, root)}
        except PackValidationError as exc:
            raise HTTPException(422, str(exc))


@router.get('/packs/{pack_id}/overview')
def pack_overview(pack_id: str, request: Request):
    with get_db(request) as db:
        try:
            return overview(db, pack_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc))


@router.get('/packs/{pack_id}/tree')
def pack_tree(pack_id: str, request: Request):
    with get_db(request) as db:
        if pack_state(db, pack_id) is None:
            raise HTTPException(404, f'内容包不存在: {pack_id}')
        nodes = db.execute(
            '''SELECT kn.*, ms.mastery_score, ms.evidence_count,
                      (SELECT COUNT(*) FROM question_node_map m WHERE m.node_id=kn.id) qcount
               FROM knowledge_nodes kn LEFT JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
               WHERE kn.pack_id=? ORDER BY kn.level, kn.sort_no, kn.code''', (pack_id,)).fetchall()
        by_parent: dict[str | None, list] = {}
        for n in nodes:
            item = {
                'id': n['id'], 'code': n['code'], 'name': n['name'], 'level': n['level'],
                'module_id': n['module_id'], 'description': n['description'],
                'questions': n['qcount'],
                'mastery': n['mastery_score'] if 'mastery_score' in n.keys() else None,
                'evidence': n['evidence_count'] if 'evidence_count' in n.keys() else 0,
                'children': [],
            }
            by_parent.setdefault(n['parent_id'], []).append(item)

        def attach(parent_id):
            return by_parent.get(parent_id, [])

        def rollup(items):
            """把子孙节点的题量与掌握度汇总到父节点，避免父级显示 0 题。"""
            for item in items:
                item['children'] = rollup(attach(item['id']))
                if item['children']:
                    item['questions'] += sum(c['questions'] for c in item['children'])
                    weighted = [(c['mastery'], c['evidence']) for c in item['children']
                                if c['mastery'] is not None and (c['evidence'] or 0) > 0]
                    if weighted:
                        total_ev = sum(w for _, w in weighted)
                        item['mastery'] = sum(m * w for m, w in weighted) / total_ev
                        item['evidence'] = total_ev
            return items

        modules = [dict(m) for m in db.execute(
            'SELECT id, name FROM modules WHERE pack_id=? ORDER BY sort_no', (pack_id,)).fetchall()]
    return {'pack_id': pack_id, 'modules': modules, 'roots': rollup(attach(None))}


@router.get('/packs/{pack_id}/assets/{asset_path:path}')
def pack_asset(pack_id: str, asset_path: str, request: Request):
    from fastapi.responses import FileResponse
    base = (get_pack_root(request) / pack_id / 'assets').resolve()
    target = (base / asset_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(404, '资源不存在')
    return FileResponse(target)


# ---------- 做题 ----------

class SessionBody(BaseModel):
    pack_id: str
    module_ids: list[str] | None = None
    count: int = 10
    mode: str = 'practice'
    seed: str | None = None


@router.post('/quiz/sessions')
def create_quiz_session(body: SessionBody, request: Request):
    with get_db(request) as db:
        try:
            return create_session(db, body.pack_id, module_ids=body.module_ids,
                                  count=body.count, mode=body.mode, seed=body.seed)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@router.get('/quiz/sessions/{session_id}')
def get_session(session_id: str, request: Request, reveal: bool = False):
    with get_db(request) as db:
        try:
            return session_detail(db, session_id, reveal=reveal)
        except LookupError as exc:
            raise HTTPException(404, str(exc))


class AnswerBody(BaseModel):
    question_id: str
    answer: str | None = None
    confidence: float | None = None
    hint_level: int = 0
    elapsed_ms: int = 0


@router.post('/quiz/sessions/{session_id}/answers')
def submit(session_id: str, body: AnswerBody, request: Request):
    with get_db(request) as db:
        try:
            return submit_answer(db, session_id, body.question_id, answer=body.answer,
                                 confidence=body.confidence, hint_level=body.hint_level,
                                 elapsed_ms=body.elapsed_ms)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@router.get('/quiz/sessions/{session_id}/result')
def get_result(session_id: str, request: Request):
    with get_db(request) as db:
        if not db.execute('SELECT 1 FROM quiz_sessions WHERE id=?', (session_id,)).fetchone():
            raise HTTPException(404, f'会话不存在: {session_id}')
        return session_result(db, session_id)


# ---------- 复习 ----------

@router.get('/review/due')
def due(pack_id: str, request: Request, limit: int = 25):
    with get_db(request) as db:
        rows = due_reviews(db, pack_id=pack_id, limit=limit)
    return {'pack_id': pack_id, 'count': len(rows),
            'items': [{'id': r['id'], 'due': r['due'], 'state': r['state'],
                       'review_count': r['review_count'], 'lapse_count': r['lapse_count']} for r in rows]}


# ---------- AI 教师 ----------

class TeacherBody(BaseModel):
    pack_id: str
    mode: str = 'chat'
    question_id: str | None = None
    message: str = ''
    history: list[dict] | None = None


@router.post('/ai/teacher')
async def ai_teacher(body: TeacherBody, request: Request):
    if body.mode not in ('hint', 'explain', 'chat'):
        raise HTTPException(400, 'mode 必须是 hint/explain/chat')
    with get_db(request) as db:
        try:
            return await teacher_reply(db, body.pack_id, body.mode, body.message,
                                       question_id=body.question_id, history=body.history)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # 模型端点/网络故障不应炸掉整个接口
            raise HTTPException(502, f'AI 服务暂不可用: {exc}')


@router.get('/ai/conversations')
def ai_history(pack_id: str, request: Request, question_id: str | None = None):
    with get_db(request) as db:
        return {'messages': conversation_history(db, pack_id, question_id)}


# ---------- 学习框架：课程 / 单元 / 诊断 ----------

class StepDoneBody(BaseModel):
    unit_id: str
    step_id: str
    pack_id: str


@router.get('/packs/{pack_id}/courses')
def list_courses(pack_id: str, request: Request):
    """列出内容包里的课程与单元，附当前进度。"""
    with get_db(request) as db:
        if pack_state(db, pack_id) is None:
            raise HTTPException(404, f'内容包不存在: {pack_id}')
        courses = []
        for c in db.execute('SELECT * FROM courses WHERE pack_id=? ORDER BY code', (pack_id,)):
            units = []
            for u in db.execute('SELECT * FROM course_units WHERE course_id=? ORDER BY sort_no, code',
                                (c['id'],)):
                try:
                    status = lesson.unit_status(db, u['id'])
                except KeyError:
                    continue
                units.append({'unit_id': u['id'], 'code': u['code'], 'title': u['title'],
                              'objective': u['objective'], 'est_minutes': u['est_minutes'],
                              'steps_done': status['steps_done'],
                              'steps_total': status['steps_total'],
                              'all_targets_met': status['all_targets_met'],
                              'done': status['all_targets_met'] and status['next_step'] is None})
            courses.append({'course_id': c['id'], 'code': c['code'], 'title': c['title'],
                            'goal': c['goal'], 'audience': c['audience'],
                            'version': c['version'], 'units': units})
    return {'pack_id': pack_id, 'courses': courses}


@router.get('/courses/{course_id:path}/next')
def next_unit(course_id: str, request: Request):
    with get_db(request) as db:
        try:
            result = lesson.next_unit(db, course_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
    return {'course_id': course_id, 'next_unit': result}


@router.get('/units/{unit_id:path}')
def get_unit(unit_id: str, request: Request):
    """单元详情：步骤清单 + 每个概念的等级与目标 + 当前卡点。"""
    with get_db(request) as db:
        try:
            status = lesson.unit_status(db, unit_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        steps = [dict(r) for r in db.execute(
            'SELECT id,ord,kind,concept_id,title,content_ref,config_json FROM unit_steps '
            'WHERE unit_id=? ORDER BY ord', (unit_id,))]
        done = {r['step_id'] for r in db.execute(
            'SELECT DISTINCT step_id FROM learning_events WHERE unit_id=? AND kind=?',
            (unit_id, 'step_viewed'))}
        for s in steps:
            s['done'] = s['id'] in done
            s['config'] = json.loads(s.pop('config_json') or '{}')
        blockers = []
        for c in status['concepts']:
            try:
                b = lesson.diagnose_blocker(db, c['concept_id'])
            except KeyError:
                continue
            if b['blocked']:
                blockers.append(b)
    return {'unit': status, 'steps': steps, 'blockers': blockers}


@router.post('/learn/steps/done')
def complete_step(body: StepDoneBody, request: Request):
    with get_db(request) as db:
        if pack_state(db, body.pack_id) is None:
            raise HTTPException(404, f'内容包不存在: {body.pack_id}')
        try:
            return lesson.advance_unit(db, body.unit_id, body.step_id, pack_id=body.pack_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))


class LearnEventBody(BaseModel):
    pack_id: str
    kind: str
    concept_id: str | None = None
    unit_id: str | None = None
    step_id: str | None = None
    hint_level: int = 0
    assisted: bool | None = None
    payload: dict | None = None


@router.post('/learn/events')
def post_learning_event(body: LearnEventBody, request: Request):
    """记录一条学习证据。等级永远由证据推导，接口不接收 level。"""
    with get_db(request) as db:
        if pack_state(db, body.pack_id) is None:
            raise HTTPException(404, f'内容包不存在: {body.pack_id}')
        if body.kind not in lesson.EVENT_KINDS:
            raise HTTPException(400, f'kind 必须是 {sorted(lesson.EVENT_KINDS)}')
        event_id = lesson.record_event(db, body.pack_id, body.kind, unit_id=body.unit_id,
                                       step_id=body.step_id, concept_id=body.concept_id,
                                       hint_level=body.hint_level, assisted=body.assisted,
                                       payload=body.payload)
        lesson.rebuild_ability(db, body.pack_id)
    return {'event_id': event_id}


@router.get('/concepts/{concept_id:path}/diagnose')
def diagnose(concept_id: str, request: Request, required_level: int | None = None):
    with get_db(request) as db:
        try:
            return lesson.diagnose_blocker(db, concept_id, required_level=required_level)
        except KeyError as exc:
            raise HTTPException(404, str(exc))


# ---------- 项目层：项目 / 交付物 / 验收 ----------

def artifact_base(request: Request) -> Path:
    """产物根目录：<data>/artifacts/<pack_id>/<project_code>，与数据库同处，便于备份。"""
    root = request.app.state.db_path
    return Path(root).parent / 'artifacts'


class DeliverableBody(BaseModel):
    payload: dict | None = Field(default=None, description='产物参数；explain 类传 {"explain": "..."}')
    assisted: bool = Field(default=False, description='是否借助提示完成')
    artifact_dir: str | None = Field(default=None, description='覆盖产物目录；用户自建项目可指向自己的仓库')


class UserProjectBody(BaseModel):
    pack_id: str
    code: str
    title: str
    brief: str = ''
    goal: str = ''
    repo_path: str | None = None


@router.get('/packs/{pack_id}/projects')
def list_projects(pack_id: str, request: Request):
    with get_db(request) as db:
        if pack_state(db, pack_id) is None:
            raise HTTPException(404, f'内容包不存在: {pack_id}')
        out = []
        for p in db.execute('SELECT id FROM projects WHERE pack_id=? ORDER BY code', (pack_id,)):
            try:
                out.append(project_mod.project_status(db, p['id']))
            except KeyError:
                continue
    return {'pack_id': pack_id, 'projects': out}


@router.get('/projects/{project_id}')
def get_project(project_id: str, request: Request):
    with get_db(request) as db:
        try:
            return project_mod.project_status(db, project_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))


@router.get('/projects/{project_id}/pending')
def list_pending(project_id: str, request: Request):
    with get_db(request) as db:
        pack = db.execute('SELECT pack_id FROM projects WHERE id=?', (project_id,)).fetchone()
        if pack is None:
            raise HTTPException(404, f'项目不存在: {project_id}')
        return {'pending': project_mod.pending_submissions(db, pack_id=pack['pack_id'])}


@router.post('/projects')
def create_user_project(body: UserProjectBody, request: Request):
    """登记学习者自己的真实项目，走同一套验收。"""
    with get_db(request) as db:
        if pack_state(db, body.pack_id) is None:
            raise HTTPException(404, f'内容包不存在: {body.pack_id}')
        return project_mod.user_project(db, body.pack_id, code=body.code, title=body.title,
                                        brief=body.brief, goal=body.goal,
                                        repo_path=body.repo_path)


@router.post('/deliverables/{deliverable_id}/submit')
def submit_deliverable(deliverable_id: str, body: DeliverableBody, request: Request):
    """提交一次交付物。返回逐项检查结果——**没通过也会如实说明哪一项没过**。"""
    base = Path(body.artifact_dir) if body.artifact_dir else artifact_base(request)
    with get_db(request) as db:
        try:
            return project_mod.submit_deliverable(db, deliverable_id, artifact_base=base,
                                                  payload=body.payload, assisted=body.assisted)
        except KeyError as exc:
            raise HTTPException(404, str(exc))


class ReviewBody(BaseModel):
    submission_id: int
    approved: bool
    reviewer: str = 'human'
    note: str = ''


def list_pending(project_id: str, request: Request):
    with get_db(request) as db:
        pack = db.execute('SELECT pack_id FROM projects WHERE id=?', (project_id,)).fetchone()
        if pack is None:
            raise HTTPException(404, f'项目不存在: {project_id}')
        return {'pending': project_mod.pending_submissions(db, pack_id=pack['pack_id'])}


@router.post('/submissions/review')
def review_submission(body: ReviewBody, request: Request):
    """解释类交付物的评审出口：pending → pass / fail。"""
    with get_db(request) as db:
        try:
            return project_mod.review_submission(db, body.submission_id,
                                                 approved=body.approved,
                                                 reviewer=body.reviewer, note=body.note)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))


# ---------- 开源社区资料导入 ----------

class ApkgBody(BaseModel):
    path: str
    pack_id: str | None = None
    pack_name: str | None = None


@router.post('/import/anki')
def import_anki(body: ApkgBody, request: Request):
    src = Path(body.path)
    if not src.is_file():
        raise HTTPException(404, f'文件不存在: {src}')
    with get_db(request) as db:
        try:
            return import_apkg(db, src, get_pack_root(request), body.pack_id, body.pack_name)
        except (PackValidationError, ValueError, KeyError) as exc:
            raise HTTPException(422, f'导入失败: {exc}')


class JsonlBody(BaseModel):
    path: str
    pack_id: str
    pack_name: str
    module_names: dict[str, str] | None = None


@router.post('/import/jsonl')
def import_jsonl_api(body: JsonlBody, request: Request):
    src = Path(body.path)
    if not src.is_file():
        raise HTTPException(404, f'文件不存在: {src}')
    with get_db(request) as db:
        try:
            return import_jsonl(db, src, get_pack_root(request), body.pack_id,
                                body.pack_name, body.module_names)
        except (ValueError, PackValidationError) as exc:
            raise HTTPException(422, f'导入失败: {exc}')
