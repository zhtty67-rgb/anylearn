"""迁移引擎：全新建库、幂等重放、外键完整性。"""
from app import db as db_mod


def test_migrate_fresh_and_idempotent(tmp_path):
    path = tmp_path / 'a.db'
    db_mod.migrate(path)
    db_mod.migrate(path)  # 幂等
    with db_mod.connect(path) as db:
        versions = [r['version'] for r in db.execute('SELECT version FROM schema_migrations')]
        assert versions == [1, 2, 3, 4]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {'packs', 'modules', 'knowledge_nodes', 'questions', 'question_node_map',
                    'quiz_sessions', 'session_questions', 'attempts', 'review_cards',
                    'review_events', 'mastery_state', 'mastery_evidence', 'ai_conversations'}
        # 003 学习框架：概念 / 先修 / 课程 / 单元 / 步骤 / 学习事件 / 能力投影
        expected |= {'concepts', 'concept_node_map', 'concept_prerequisites', 'courses',
                     'course_units', 'unit_concepts', 'unit_steps', 'learning_events',
                     'concept_ability', 'unit_progress'}
        # 004 项目层：项目 / 门禁 / 里程碑 / 交付物 / 提交证据 / 进度投影
        expected |= {'projects', 'project_requirements', 'project_milestones',
                     'project_deliverables', 'project_concepts', 'deliverable_submissions',
                     'milestone_progress', 'project_progress'}
        assert expected <= tables


def test_cutoff_cannot_downgrade(tmp_path):
    path = tmp_path / 'b.db'
    db_mod.migrate(path)
    try:
        db_mod.migrate(path, target_version=0)
        assert False, '应拒绝降级'
    except RuntimeError:
        pass
