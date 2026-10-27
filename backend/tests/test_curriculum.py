"""curriculum.json 加载：内容包里的课程能被装载成可执行的教学结构。"""
import json

import pytest

from app.contentpack.loader import PackValidationError, install_pack


def _write_curriculum(pack_dir, curriculum):
    (pack_dir / 'data' / 'curriculum.json').write_text(
        json.dumps(curriculum, ensure_ascii=False), encoding='utf-8')


def _minimal_curriculum(**over):
    base = {
        'concepts': [
            {'code': 'c1', 'name': '概念一', 'module_id': 'mod-a', 'summary': '定义一',
             'misconceptions': ['误解一'], 'prerequisites': []},
            {'code': 'c2', 'name': '概念二', 'module_id': 'mod-a', 'summary': '定义二',
             'prerequisites': ['c1']},
        ],
        'courses': [{
            'code': 'course-x', 'title': '课程X', 'goal': '目标X', 'version': '1.0.0',
            'units': [{
                'code': 'u1', 'title': '单元一', 'objective': '目标一', 'est_minutes': 20,
                'concepts': [{'code': 'c2', 'role': 'core', 'target_level': 3}],
                'steps': [
                    {'kind': 'diagnose', 'concept': 'c2'},
                    {'kind': 'explain', 'concept': 'c2'},
                    {'kind': 'verify', 'concept': 'c2'},
                ],
            }],
        }],
    }
    base.update(over)
    return base


def test_curriculum_installs(tmp_path, content_root, db):
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    result = install_pack(db, content_root / 'demo-pack')
    assert result['concepts'] == 2 and result['units'] == 1

    concepts = {r['code'] for r in db.execute('SELECT code FROM concepts')}
    assert concepts == {'c1', 'c2'}
    pre = db.execute('SELECT 1 FROM concept_prerequisites').fetchall()
    assert len(pre) == 1
    steps = [r['kind'] for r in db.execute('SELECT kind FROM unit_steps ORDER BY ord')]
    assert steps == ['diagnose', 'explain', 'verify']


def test_pack_without_curriculum_still_works(tmp_path, content_root, db):
    result = install_pack(db, content_root / 'demo-pack')
    assert result['concepts'] == 0 and result['courses'] == 0
    assert db.execute('SELECT COUNT(*) c FROM questions').fetchone()['c'] == 5


def test_unknown_prerequisite_rejected(tmp_path, content_root, db):
    c = _minimal_curriculum()
    c['concepts'][1]['prerequisites'] = ['nope']
    _write_curriculum(content_root / 'demo-pack', c)
    with pytest.raises(PackValidationError, match='先修'):
        install_pack(db, content_root / 'demo-pack')


def test_self_prerequisite_rejected(tmp_path, content_root, db):
    c = _minimal_curriculum()
    c['concepts'][0]['prerequisites'] = ['c1']
    _write_curriculum(content_root / 'demo-pack', c)
    with pytest.raises(PackValidationError, match='先修'):
        install_pack(db, content_root / 'demo-pack')


def test_unknown_step_kind_rejected(tmp_path, content_root, db):
    c = _minimal_curriculum()
    c['courses'][0]['units'][0]['steps'][0]['kind'] = 'lecture-ish'
    _write_curriculum(content_root / 'demo-pack', c)
    with pytest.raises(PackValidationError, match='kind'):
        install_pack(db, content_root / 'demo-pack')


def test_bad_target_level_rejected(tmp_path, content_root, db):
    c = _minimal_curriculum()
    c['courses'][0]['units'][0]['concepts'][0]['target_level'] = 9
    _write_curriculum(content_root / 'demo-pack', c)
    with pytest.raises(PackValidationError, match='target_level'):
        install_pack(db, content_root / 'demo-pack')


def test_reinstall_keeps_learning_events(tmp_path, content_root, db):
    """升级内容包不应清掉已有的学习事件（和作答一样是事实源）。"""
    from app.domain import lesson
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    install_pack(db, content_root / 'demo-pack')
    lesson.record_event(db, 'demo-pack', 'attempt', concept_id='demo-pack:c2', assisted=0)
    install_pack(db, content_root / 'demo-pack', force=True)
    assert db.execute('SELECT COUNT(*) c FROM learning_events').fetchone()['c'] == 1


# ---------------------------------------------------------------- 项目层
def _write_projects(pack_dir, data):
    (pack_dir / 'data' / 'projects.json').write_text(
        json.dumps(data, ensure_ascii=False), encoding='utf-8')


def _project_data(**over):
    base = {'projects': [{
        'code': 'p1', 'title': '项目一', 'brief': '简介', 'goal': '目标',
        'requires': [{'course': 'course-x', 'unit': 'u1', 'min_level': 3}],
        'concepts': [{'code': 'c2', 'target_level': 5}],
        'milestones': [{
            'code': 'm1', 'title': '里程碑一',
            'deliverables': [
                {'code': 'd1', 'title': '脚本', 'kind': 'run',
                 'acceptance': {'cmd': 'python x.py', 'expect_exit': 0}},
                {'code': 'd2', 'title': '解释', 'kind': 'explain',
                 'acceptance': {'min_chars': 10, 'rubric': ['要点一']}},
            ]}]}]}
    base.update(over)
    return base


def test_projects_install(tmp_path, content_root, db):
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    _write_projects(content_root / 'demo-pack', _project_data())
    result = install_pack(db, content_root / 'demo-pack')
    assert result['projects'] == 1
    assert db.execute('SELECT COUNT(*) c FROM project_milestones').fetchone()['c'] == 1
    assert db.execute('SELECT COUNT(*) c FROM project_deliverables').fetchone()['c'] == 2
    assert db.execute('SELECT COUNT(*) c FROM project_requirements').fetchone()['c'] == 1
    assert db.execute('SELECT COUNT(*) c FROM project_concepts').fetchone()['c'] == 1


def test_project_requirement_must_reference_existing_unit(tmp_path, content_root, db):
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    data = _project_data()
    data['projects'][0]['requires'] = [{'course': 'course-x', 'unit': 'nope'}]
    _write_projects(content_root / 'demo-pack', data)
    with pytest.raises(PackValidationError, match='单元不存在'):
        install_pack(db, content_root / 'demo-pack')


def test_project_concept_must_exist(tmp_path, content_root, db):
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    data = _project_data()
    data['projects'][0]['concepts'] = [{'code': 'ghost'}]
    _write_projects(content_root / 'demo-pack', data)
    with pytest.raises(PackValidationError, match='不存在的概念'):
        install_pack(db, content_root / 'demo-pack')


def test_bad_deliverable_kind_rejected(tmp_path, content_root, db):
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    data = _project_data()
    data['projects'][0]['milestones'][0]['deliverables'][0]['kind'] = 'magic'
    _write_projects(content_root / 'demo-pack', data)
    with pytest.raises(PackValidationError, match='kind'):
        install_pack(db, content_root / 'demo-pack')


def test_reinstall_keeps_user_projects(tmp_path, content_root, db):
    _write_curriculum(content_root / 'demo-pack', _minimal_curriculum())
    _write_projects(content_root / 'demo-pack', _project_data())
    install_pack(db, content_root / 'demo-pack')
    from app.domain import project as proj
    proj.user_project(db, 'demo-pack', code='mine', title='我的项目', brief='', goal='')
    install_pack(db, content_root / 'demo-pack', force=True)
    rows = db.execute("SELECT code FROM projects WHERE authored_by='user'").fetchall()
    assert [r['code'] for r in rows] == ['mine']
