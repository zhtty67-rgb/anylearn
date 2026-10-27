"""内容包（Content Pack）协议与加载器 —— 框架的注入点。

一个内容包是一个目录：
    content-packs/<pack-id>/
        pack.yaml               清单：名称/版本/模块/主题/AI人设/判分策略
        data/knowledge_tree.json 知识树：模块 > 章节 > 考点
        data/questions.jsonl     题目，每行一题
        assets/                  可选静态资源（图片等）

放入 content-packs/ 后启动应用即自动安装；同名同版本跳过，版本升级则更新。
框架代码不包含任何领域内容 —— 注入什么内容包，就变成什么学习系统。
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

QUESTION_TYPES = {'single_choice', 'multi_choice', 'cloze', 'self_rate', 'short_answer'}


class PackValidationError(Exception):
    """内容包不符合协议时抛出，附带可读的原因。"""


def _valid_id(value) -> bool:
    return bool(isinstance(value, str) and re.fullmatch(r'[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff_-]*', value))


def discover_packs(root: Path) -> list[Path]:
    """扫描内容包根目录，返回所有含 pack.yaml 的子目录（跳过 _ 模板与隐藏目录）。"""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(('_', '.'))
                  and (p / 'pack.yaml').is_file())


def load_manifest(pack_dir: Path) -> dict:
    """读取并校验 pack.yaml，返回规范化后的清单 dict。"""
    pack_dir = Path(pack_dir)
    manifest_path = pack_dir / 'pack.yaml'
    if not manifest_path.is_file():
        raise PackValidationError(f'缺少 pack.yaml: {manifest_path}')
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError as exc:
        raise PackValidationError(f'pack.yaml 解析失败: {exc}') from exc

    pack_id = raw.get('id') or pack_dir.name
    if not _valid_id(pack_id):
        raise PackValidationError(f'非法内容包 id: {pack_id!r}（仅小写字母/数字/-/_）')
    if not raw.get('name'):
        raise PackValidationError('pack.yaml 缺少 name')

    modules = raw.get('modules') or []
    seen = set()
    for m in modules:
        mid = m.get('id') if isinstance(m, dict) else None
        if not _valid_id(mid):
            raise PackValidationError(f'模块 id 非法: {mid!r}')
        if mid in seen:
            raise PackValidationError(f'模块 id 重复: {mid}')
        seen.add(mid)
        if not m.get('name'):
            raise PackValidationError(f'模块 {mid} 缺少 name')

    manifest = {
        'id': pack_id,
        'name': str(raw['name']),
        'version': str(raw.get('version', '1.0.0')),
        'description': str(raw.get('description', '')),
        'modules': modules,
        'theme': raw.get('theme') or {},
        'ai': raw.get('ai') or {},
        'grading': raw.get('grading') or {'mode': 'objective'},
        'source': raw.get('source') or {},
    }
    return manifest


def _load_tree(pack_dir: Path, manifest: dict) -> tuple[list[dict], list[dict]]:
    """读取 knowledge_tree.json，返回 (nodes, node_question_bindings)。"""
    tree_path = pack_dir / 'data' / 'knowledge_tree.json'
    if not tree_path.is_file():
        return [], []
    data = json.loads(tree_path.read_text(encoding='utf-8'))
    module_ids = {m['id'] for m in manifest['modules']}
    nodes, bindings = [], []

    def walk(items, parent_code, parent_module, level):
        for sort_no, item in enumerate(items):
            code = item.get('code') or item.get('id')
            if not code:
                raise PackValidationError(f'知识树节点缺少 code: {item}')
            module_id = item.get('module_id') or parent_module
            if level == 1:
                if module_id not in module_ids:
                    raise PackValidationError(
                        f'一级节点 {code} 未在 pack.yaml modules 中声明（module_id={module_id}）'
                    )
            nodes.append({
                'code': str(code),
                'module_id': str(module_id),
                'parent_code': parent_code,
                'name': str(item.get('name', code)),
                'description': str(item.get('description', '')),
                'weight': float(item.get('weight', 1.0)),
                'level': level,
                'sort_no': sort_no,
            })
            for qid in item.get('question_ids') or []:
                bindings.append({'question_id': str(qid), 'node_code': str(code),
                                 'weight': 1.0, 'from_tree': True})
            walk(item.get('children') or [], str(code), str(module_id), level + 1)

    walk(data if isinstance(data, list) else data.get('nodes', []), None, None, 1)
    return nodes, bindings


def _iter_questions(pack_dir: Path, manifest: dict):
    """流式读取 questions.jsonl 并逐条校验。"""
    path = pack_dir / 'data' / 'questions.jsonl'
    if not path.is_file():
        return
    module_ids = {m['id'] for m in manifest['modules']}
    with path.open(encoding='utf-8') as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            try:
                q = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PackValidationError(f'questions.jsonl 第 {line_no} 行不是合法 JSON: {exc}') from exc
            for field in ('id', 'module', 'type', 'stem', 'answer'):
                if not q.get(field):
                    raise PackValidationError(f'questions.jsonl 第 {line_no} 行缺少字段 {field}')
            if q['type'] not in QUESTION_TYPES:
                raise PackValidationError(f'第 {line_no} 行非法题型 {q["type"]!r}，支持: {sorted(QUESTION_TYPES)}')
            if q['module'] not in module_ids:
                raise PackValidationError(f'第 {line_no} 行 module={q["module"]!r} 未在 pack.yaml 声明')
            if q['type'] == 'single_choice':
                options = q.get('options') or []
                if len(options) < 2:
                    raise PackValidationError(f'第 {line_no} 行 single_choice 至少需要 2 个选项')
                answer = str(q['answer']).strip().upper()
                if answer not in 'ABCDEFGH'[: len(options)]:
                    raise PackValidationError(f'第 {line_no} 行 answer={answer!r} 必须是选项字母')
                q['answer'] = answer
                q['options'] = [str(o) for o in options]
            elif q['type'] == 'multi_choice':
                options = q.get('options') or []
                if len(options) < 2:
                    raise PackValidationError(f'第 {line_no} 行 multi_choice 至少需要 2 个选项')
                letters = {c for c in str(q['answer']).strip().upper() if c.isalpha()}
                valid = set('ABCDEFGH'[: len(options)])
                if len(letters) < 2 or not letters <= valid:
                    raise PackValidationError(
                        f'第 {line_no} 行 multi_choice answer={q["answer"]!r} 必须是至少两个有效选项字母，如 "ABC"')
                q['answer'] = ''.join(sorted(letters))
                q['options'] = [str(o) for o in options]
            yield q


def _version_key(version: str):
    try:
        return tuple(int(p) for p in str(version).split('.'))
    except ValueError:
        return (0,)


# ------------------------------------------------------------------ 学习框架
STEP_KINDS = {'diagnose', 'explain', 'socratic', 'feynman', 'practice', 'verify', 'review'}
CONCEPT_ROLES = {'core', 'support', 'prereq'}


def _load_courses(pack_dir: Path, manifest: dict):
    """读取 data/curriculum.json（可选）：概念 / 先修 / 课程 / 单元 / 步骤。

    与 knowledge_tree 的分工：知识树描述「有哪些知识点」，课程描述「怎么教」。
    没有 curriculum.json 的包照常工作，只是不提供学习单元。
    """
    path = pack_dir / 'data' / 'curriculum.json'
    if not path.is_file():
        return {'concepts': [], 'prerequisites': [], 'courses': []}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise PackValidationError(f'curriculum.json 解析失败: {exc}') from exc

    module_ids = {m['id'] for m in manifest['modules']}
    concepts = raw.get('concepts') or []
    seen = set()
    for c in concepts:
        code = c.get('code')
        if not _valid_id(code):
            raise PackValidationError(f'概念 code 非法: {code!r}')
        if code in seen:
            raise PackValidationError(f'概念 code 重复: {code}')
        seen.add(code)
        if not c.get('name'):
            raise PackValidationError(f'概念 {code} 缺少 name')
        if c.get('module_id') and c['module_id'] not in module_ids:
            raise PackValidationError(f'概念 {code} 的 module_id 未声明: {c["module_id"]}')

    prereqs = []
    for c in concepts:
        for pre in c.get('prerequisites') or []:
            if pre not in seen:
                raise PackValidationError(f'概念 {c["code"]} 的先修 {pre!r} 不存在')
            if pre == c['code']:
                raise PackValidationError(f'概念 {c["code"]} 不能把自己列为先修')
            prereqs.append({'concept': c['code'], 'prerequisite': pre,
                            'strength': float(c.get('strength', 1.0))})

    courses = []
    for course in raw.get('courses') or []:
        cc = course.get('code')
        if not _valid_id(cc):
            raise PackValidationError(f'课程 code 非法: {cc!r}')
        units = []
        for u in course.get('units') or []:
            uc = u.get('code')
            if not _valid_id(uc):
                raise PackValidationError(f'课程 {cc} 的单元 code 非法: {uc!r}')
            uconcepts = []
            for item in u.get('concepts') or []:
                code = item.get('code') if isinstance(item, dict) else item
                if code not in seen:
                    raise PackValidationError(f'单元 {uc} 引用了不存在的概念: {code!r}')
                role = (item.get('role') if isinstance(item, dict) else None) or 'core'
                if role not in CONCEPT_ROLES:
                    raise PackValidationError(f'单元 {uc} 概念 {code} 的 role 非法: {role}')
                target = int(item.get('target_level', 3)) if isinstance(item, dict) else 3
                if not 1 <= target <= 5:
                    raise PackValidationError(f'单元 {uc} 概念 {code} 的 target_level 须在 1..5')
                uconcepts.append({'code': code, 'role': role, 'target_level': target})
            steps = []
            for ord_no, s in enumerate(u.get('steps') or [], 1):
                if s.get('kind') not in STEP_KINDS:
                    raise PackValidationError(
                        f'单元 {uc} 第 {ord_no} 步 kind 非法: {s.get("kind")!r}，支持 {sorted(STEP_KINDS)}')
                if s.get('concept') and s['concept'] not in seen:
                    raise PackValidationError(f'单元 {uc} 步骤引用了不存在的概念: {s["concept"]}')
                steps.append({'ord': ord_no, 'kind': s['kind'], 'concept': s.get('concept'),
                              'title': s.get('title', ''), 'content_ref': s.get('content_ref'),
                              'config': s.get('config') or {}})
            units.append({
                'code': uc, 'title': u.get('title') or uc,
                'objective': u.get('objective', ''),
                'sort_no': float(u.get('sort_no', len(units) + 1)),
                'est_minutes': int(u.get('est_minutes', 30)),
                'concepts': uconcepts, 'steps': steps,
            })
        courses.append({'code': cc, 'title': course.get('title') or cc,
                        'goal': course.get('goal', ''), 'audience': course.get('audience', ''),
                        'version': str(course.get('version', '1.0.0')), 'units': units})
    return {'concepts': concepts, 'prerequisites': prereqs, 'courses': courses}


# ------------------------------------------------------------------ 项目层
DELIVERABLE_KINDS = {'file', 'test', 'run', 'explain', 'data'}


def _load_projects(pack_dir: Path, curriculum: dict):
    """读取 data/projects.json（可选）：项目 / 门禁 / 里程碑 / 交付物 / 概念映射。"""
    path = pack_dir / 'data' / 'projects.json'
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise PackValidationError(f'projects.json 解析失败: {exc}') from exc
    if not isinstance(raw, dict):
        raise PackValidationError('projects.json 顶层必须是对象 {"projects": [...]}')

    concept_codes = {c['code'] for c in curriculum['concepts']}
    course_units = {}
    for course in curriculum['courses']:
        course_units[course['code']] = {u['code'] for u in course['units']}

    projects = []
    for p in raw.get('projects') or []:
        code = p.get('code')
        if not _valid_id(code):
            raise PackValidationError(f'项目 code 非法: {code!r}')
        if not p.get('title'):
            raise PackValidationError(f'项目 {code} 缺少 title')

        reqs = []
        for r in p.get('requires') or []:
            ccode = r.get('course')
            ucode = r.get('unit')
            if ccode not in course_units:
                raise PackValidationError(f'项目 {code} 要求的课程不存在: {ccode!r}')
            if ucode not in course_units[ccode]:
                raise PackValidationError(f'项目 {code} 要求的单元不存在: {ucode!r}')
            lvl = int(r.get('min_level', 3))
            if not 1 <= lvl <= 5:
                raise PackValidationError(f'项目 {code} 的 min_level 须在 1..5')
            reqs.append({'course': ccode, 'unit': ucode, 'min_level': lvl})

        concepts = []
        for c in p.get('concepts') or []:
            ccode = c.get('code') if isinstance(c, dict) else c
            if ccode not in concept_codes:
                raise PackValidationError(f'项目 {code} 引用了不存在的概念: {ccode!r}')
            target = int(c.get('target_level', 4)) if isinstance(c, dict) else 4
            if not 1 <= target <= 5:
                raise PackValidationError(f'项目 {code} 概念的 target_level 须在 1..5')
            concepts.append({'code': ccode, 'target_level': target})

        milestones = []
        for m in p.get('milestones') or []:
            mcode = m.get('code')
            if not _valid_id(mcode):
                raise PackValidationError(f'项目 {code} 里程碑 code 非法: {mcode!r}')
            deliverables = []
            for d in m.get('deliverables') or []:
                dcode = d.get('code')
                if not _valid_id(dcode):
                    raise PackValidationError(f'里程碑 {mcode} 交付物 code 非法: {dcode!r}')
                kind = d.get('kind')
                if kind not in DELIVERABLE_KINDS:
                    raise PackValidationError(
                        f'交付物 {dcode} 的 kind 非法: {kind!r}，支持 {sorted(DELIVERABLE_KINDS)}')
                deliverables.append({'code': dcode, 'title': d.get('title') or dcode,
                                     'kind': kind, 'required': bool(d.get('required', True)),
                                     'acceptance': d.get('acceptance') or {}})
            milestones.append({'code': mcode, 'title': m.get('title') or mcode,
                               'objective': m.get('objective', ''),
                               'sort_no': float(m.get('sort_no', len(milestones) + 1)),
                               'est_minutes': int(m.get('est_minutes', 60)),
                               'deliverables': deliverables})
        projects.append({'code': code, 'title': p['title'], 'brief': p.get('brief', ''),
                         'goal': p.get('goal', ''), 'requires': reqs,
                         'concepts': concepts, 'milestones': milestones})
    return projects


def _install_curriculum(db, pack_id: str, curriculum: dict, now: str):
    """把 curriculum 写入库：概念/先修/课程/单元/步骤全量刷新，作答与事件保留。"""
    db.execute('DELETE FROM concept_prerequisites WHERE concept_id IN '
               '(SELECT id FROM concepts WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM concept_node_map WHERE concept_id IN '
               '(SELECT id FROM concepts WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM unit_steps WHERE unit_id IN (SELECT u.id FROM course_units u '
               'JOIN courses c ON c.id=u.course_id WHERE c.pack_id=?)', (pack_id,))
    db.execute('DELETE FROM unit_concepts WHERE unit_id IN (SELECT u.id FROM course_units u '
               'JOIN courses c ON c.id=u.course_id WHERE c.pack_id=?)', (pack_id,))
    db.execute('DELETE FROM course_units WHERE course_id IN '
               '(SELECT id FROM courses WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM courses WHERE pack_id=?', (pack_id,))
    db.execute('DELETE FROM concepts WHERE pack_id=?', (pack_id,))

    for c in curriculum['concepts']:
        db.execute(
            '''INSERT INTO concepts
               (id,pack_id,code,module_id,name,summary,misconceptions_json,created_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (f'{pack_id}:{c["code"]}', pack_id, c['code'], str(c.get('module_id') or ''),
             c['name'], str(c.get('summary', '')),
             json.dumps(c.get('misconceptions') or [], ensure_ascii=False), now),
        )
    for p in curriculum['prerequisites']:
        db.execute('INSERT OR IGNORE INTO concept_prerequisites '
                   '(concept_id,prerequisite_id,strength) VALUES (?,?,?)',
                   (f'{pack_id}:{p["concept"]}', f'{pack_id}:{p["prerequisite"]}', p['strength']))

    for course in curriculum['courses']:
        course_id = f'{pack_id}:{course["code"]}'
        db.execute(
            '''INSERT INTO courses (id,pack_id,code,title,goal,audience,version,created_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (course_id, pack_id, course['code'], course['title'], course['goal'],
             course['audience'], course['version'], now),
        )
        for u in course['units']:
            unit_id = f'{course_id}:{u["code"]}'
            db.execute(
                '''INSERT INTO course_units (id,course_id,code,title,objective,sort_no,est_minutes)
                   VALUES (?,?,?,?,?,?,?)''',
                (unit_id, course_id, u['code'], u['title'], u['objective'], u['sort_no'],
                 u['est_minutes']),
            )
            for item in u['concepts']:
                db.execute('INSERT INTO unit_concepts (unit_id,concept_id,target_level,role) '
                           'VALUES (?,?,?,?)',
                           (unit_id, f'{pack_id}:{item["code"]}', item['target_level'], item['role']))
            for s in u['steps']:
                db.execute(
                    '''INSERT INTO unit_steps
                       (id,unit_id,ord,kind,concept_id,title,content_ref,config_json)
                       VALUES (?,?,?,?,?,?,?,?)''',
                    (f'{unit_id}:s{s["ord"]}', unit_id, s['ord'], s['kind'],
                     f'{pack_id}:{s["concept"]}' if s['concept'] else None,
                     s['title'], s['content_ref'],
                     json.dumps(s['config'], ensure_ascii=False)),
                )


def _install_projects(db, pack_id: str, projects: list, now: str):
    """项目全量刷新。提交历史与学习事件不受影响（和作答一样是事实源）。"""
    for table in ('project_requirements', 'project_concepts'):
        db.execute(f'DELETE FROM {table} WHERE project_id IN '
                   '(SELECT id FROM projects WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM project_deliverables WHERE milestone_id IN '
               '(SELECT id FROM project_milestones WHERE project_id IN '
               '(SELECT id FROM projects WHERE pack_id=?))', (pack_id,))
    db.execute('DELETE FROM project_milestones WHERE project_id IN '
               '(SELECT id FROM projects WHERE pack_id=?)', (pack_id,))
    db.execute("DELETE FROM projects WHERE pack_id=? AND authored_by='content'", (pack_id,))

    for p in projects:
        pid = f'{pack_id}:{p["code"]}'
        db.execute(
            '''INSERT INTO projects (id,pack_id,code,title,brief,goal,authored_by,repo_path,created_at)
               VALUES (?,?,?,?,?,?,'content',NULL,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, brief=excluded.brief,
                 goal=excluded.goal''',
            (pid, pack_id, p['code'], p['title'], p['brief'], p['goal'], now))
        for r in p['requires']:
            unit_id = f'{pack_id}:{r["course"]}:{r["unit"]}'
            if db.execute('SELECT 1 FROM course_units WHERE id=?', (unit_id,)).fetchone():
                db.execute('INSERT OR IGNORE INTO project_requirements (project_id,unit_id,min_level)'
                           ' VALUES (?,?,?)', (pid, unit_id, r['min_level']))
        for c in p['concepts']:
            db.execute('INSERT OR IGNORE INTO project_concepts (project_id,concept_id,target_level)'
                       ' VALUES (?,?,?)', (pid, f'{pack_id}:{c["code"]}', c['target_level']))
        for m in p['milestones']:
            mid = f'{pid}:{m["code"]}'
            db.execute(
                '''INSERT INTO project_milestones
                   (id,project_id,code,title,objective,sort_no,est_minutes)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                     objective=excluded.objective, sort_no=excluded.sort_no,
                     est_minutes=excluded.est_minutes''',
                (mid, pid, m['code'], m['title'], m['objective'], m['sort_no'], m['est_minutes']))
            for i, d in enumerate(m['deliverables']):
                db.execute(
                    '''INSERT INTO project_deliverables
                       (id,milestone_id,code,title,kind,required,acceptance_json,sort_no)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET title=excluded.title, kind=excluded.kind,
                         required=excluded.required, acceptance_json=excluded.acceptance_json''',
                    (f'{mid}:{d["code"]}', mid, d['code'], d['title'], d['kind'],
                     int(d['required']),
                     json.dumps(d['acceptance'], ensure_ascii=False), float(i + 1)))


def pack_state(db, pack_id: str):
    row = db.execute('SELECT * FROM packs WHERE id=?', (pack_id,)).fetchone()
    return dict(row) if row else None


def install_pack(db, pack_dir: Path, *, force: bool = False) -> dict:
    """安装/升级一个内容包。幂等：同版本跳过，高版本替换（保护已有作答历史）。

    替换策略：modules/nodes/questions 全量刷新；已被作答引用的旧题目若不在
    新包中则保留，避免破坏 attempts 外键与复习历史。安装后重建复习与掌握度投影。
    """
    from ..domain.review import rebuild_reviews
    from ..domain.mastery import rebuild_mastery

    manifest = load_manifest(pack_dir)
    pack_id = manifest['id']
    existing = pack_state(db, pack_id)
    if existing and not force:
        if _version_key(manifest['version']) <= _version_key(existing['version']):
            return {'pack_id': pack_id, 'status': 'unchanged', 'version': existing['version']}

    now = datetime.now(timezone.utc).isoformat()
    nodes, tree_bindings = _load_tree(pack_dir, manifest)
    node_ids = {f'{pack_id}:{n["code"]}' for n in nodes}
    questions, bindings = [], tree_bindings
    for q in _iter_questions(pack_dir, manifest):
        questions.append(q)
        for node_code in q.get('nodes') or []:
            bindings.append({'question_id': str(q['id']), 'node_code': str(node_code), 'weight': 1.0})

    qids = {str(q['id']) for q in questions}
    valid_bindings = []
    for b in bindings:
        if b['question_id'] not in qids:
            # 升级场景：知识树可能仍引用已移除的题目，跳过该绑定而非整体失败
            if b.get('from_tree'):
                continue
            raise PackValidationError(f'题目绑定引用了不存在的题目: {b["question_id"]}')
        if f'{pack_id}:{b["node_code"]}' not in node_ids:
            raise PackValidationError(f'题目绑定了不存在的知识节点: {b["node_code"]}')
        valid_bindings.append(b)

    db.execute(
        '''INSERT INTO packs (id,name,version,description,manifest_json,installed_at,updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, version=excluded.version,
             description=excluded.description, manifest_json=excluded.manifest_json,
             updated_at=excluded.updated_at''',
        (pack_id, manifest['name'], manifest['version'], manifest['description'],
         json.dumps(manifest, ensure_ascii=False), existing['installed_at'] if existing else now, now),
    )
    db.execute('DELETE FROM modules WHERE pack_id=?', (pack_id,))
    for sort_no, m in enumerate(manifest['modules']):
        db.execute('INSERT INTO modules (pack_id,id,name,sort_no) VALUES (?,?,?,?)',
                   (pack_id, m['id'], m['name'], float(m.get('sort_no', sort_no))))

    # 知识树全量刷新（掌握度投影随后重建）
    db.execute('DELETE FROM question_node_map WHERE node_id IN (SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM mastery_state WHERE knowledge_node_id IN (SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM mastery_evidence WHERE knowledge_node_id IN (SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
    db.execute('DELETE FROM knowledge_nodes WHERE pack_id=?', (pack_id,))
    for n in nodes:
        parent_id = f'{pack_id}:{n["parent_code"]}' if n['parent_code'] else None
        db.execute(
            '''INSERT INTO knowledge_nodes
               (id,pack_id,code,module_id,parent_id,name,description,weight,level,sort_no,metadata_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (f'{pack_id}:{n["code"]}', pack_id, n['code'], n['module_id'], parent_id,
             n['name'], n['description'], n['weight'], n['level'], float(n['sort_no']), '{}'),
        )

    # 题目：新包全量 upsert；旧包中被作答引用但已移除的题目保留
    attempted = {r['id'] for r in db.execute(
        'SELECT DISTINCT q.id FROM questions q JOIN attempts a ON a.question_id=q.id WHERE q.pack_id=?', (pack_id,))}
    stale = [r['id'] for r in db.execute('SELECT id FROM questions WHERE pack_id=?', (pack_id,))]
    for qid in stale:
        if qid not in qids and qid not in attempted:
            db.execute('DELETE FROM question_node_map WHERE question_id=?', (qid,))
            db.execute('DELETE FROM questions WHERE id=?', (qid,))
    for q in questions:
        db.execute(
            '''INSERT INTO questions
               (id,pack_id,module_id,type,stem,options_json,answer,explanation,difficulty,
                estimated_seconds,image_path,tags_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET module_id=excluded.module_id, type=excluded.type,
                 stem=excluded.stem, options_json=excluded.options_json, answer=excluded.answer,
                 explanation=excluded.explanation, difficulty=excluded.difficulty,
                 estimated_seconds=excluded.estimated_seconds, image_path=excluded.image_path,
                 tags_json=excluded.tags_json''',
            (str(q['id']), pack_id, q['module'], q['type'], q['stem'],
             json.dumps(q.get('options') or [], ensure_ascii=False), str(q['answer']),
             str(q.get('explanation', '')), int(q.get('difficulty', 3)),
             int(q.get('estimated_seconds', 60)), q.get('image_path'),
             json.dumps(q.get('tags') or [], ensure_ascii=False), now),
        )
    for b in valid_bindings:
        db.execute(
            'INSERT OR IGNORE INTO question_node_map (question_id,node_id,weight) VALUES (?,?,?)',
            (b['question_id'], f'{pack_id}:{b["node_code"]}', float(b.get('weight', 1.0))),
        )

    curriculum = _load_courses(pack_dir, manifest)
    # 先清项目（它对单元/概念有外键），再装课程，最后装项目
    _install_projects(db, pack_id, [], now)
    _install_curriculum(db, pack_id, curriculum, now)
    projects = _load_projects(pack_dir, curriculum)
    _install_projects(db, pack_id, projects, now)

    rebuild_reviews(db, pack_id=pack_id)
    rebuild_mastery(db, pack_id=pack_id)
    return {
        'pack_id': pack_id,
        'status': 'upgraded' if existing else 'installed',
        'version': manifest['version'],
        'modules': len(manifest['modules']),
        'nodes': len(nodes),
        'questions': len(questions),
        'concepts': len(curriculum['concepts']),
        'courses': len(curriculum['courses']),
        'units': sum(len(c['units']) for c in curriculum['courses']),
        'projects': len(projects),
    }


def install_all(db, root: Path) -> list[dict]:
    results = []
    for pack_dir in discover_packs(root):
        try:
            results.append(install_pack(db, pack_dir))
        except PackValidationError as exc:
            results.append({'pack_id': pack_dir.name, 'status': 'error', 'error': str(exc)})
    return results
