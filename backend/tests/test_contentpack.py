"""内容包协议：安装、幂等、升级、防破坏、校验拦截。"""
import pytest
import yaml

from app import db as db_mod
from app.contentpack.loader import PackValidationError, install_pack, pack_state
from tests.conftest import QUESTIONS, make_pack


@pytest.fixture
def raw_db(tmp_path):
    path = tmp_path / 'raw.db'
    db_mod.migrate(path)
    with db_mod.connect(path) as conn:
        yield conn


def test_install_populates_everything(installed_db):
    db = installed_db
    assert pack_state(db, 'demo-pack')['version'] == '1.0.0'
    assert db.execute("SELECT COUNT(*) c FROM questions WHERE pack_id='demo-pack'").fetchone()['c'] == 5
    # 树：模块级2 + 章节2 + 考点2 = 6 节点
    assert db.execute("SELECT COUNT(*) c FROM knowledge_nodes WHERE pack_id='demo-pack'").fetchone()['c'] == 6
    # 题目-考点绑定（树绑定与 nodes 字段绑定为同一批，去重后共5条）
    assert db.execute('SELECT COUNT(*) c FROM question_node_map').fetchone()['c'] == 5
    # 子节点继承模块
    child = db.execute("SELECT module_id FROM knowledge_nodes WHERE code='a-1-1'").fetchone()
    assert child['module_id'] == 'mod-a'


def test_install_idempotent_same_version(db, content_root):
    first = install_pack(db, content_root / 'demo-pack')
    assert first['status'] == 'installed'
    again = install_pack(db, content_root / 'demo-pack')
    assert again['status'] == 'unchanged'


def test_version_upgrade_and_stale_protection(db, content_root):
    from app.domain.quiz import create_session, submit_answer
    install_pack(db, content_root / 'demo-pack')
    s = create_session(db, 'demo-pack', module_ids=['mod-a'], count=5)
    submit_answer(db, s['session_id'], 'q1', answer='A')

    upgraded = make_pack(content_root, version='2.0.0',
                         questions=[q for q in QUESTIONS if q['id'] != 'q5'])
    result = install_pack(db, upgraded)
    assert result['status'] == 'upgraded'
    ids = {r['id'] for r in db.execute('SELECT id FROM questions')}
    assert 'q5' not in ids          # 未作答的旧题被清理
    assert 'q1' in ids              # 已作答的旧题受保护
    assert db.execute('SELECT COUNT(*) c FROM attempts').fetchone()['c'] == 1


def test_validation_rejects_missing_name(raw_db, tmp_path):
    d = tmp_path / 'bad'
    (d / 'data').mkdir(parents=True)
    (d / 'pack.yaml').write_text(yaml.safe_dump({'id': 'x', 'version': '1.0.0'}), encoding='utf-8')
    with pytest.raises(PackValidationError):
        install_pack(raw_db, d)


def test_validation_rejects_unknown_module(raw_db, tmp_path):
    import json
    d = make_pack(tmp_path / 'packs2', pack_id='bad-module')
    tree = [{'code': 'x', 'name': 'X', 'module_id': 'not-declared', 'children': []}]
    (d / 'data' / 'knowledge_tree.json').write_text(json.dumps(tree, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(PackValidationError):
        install_pack(raw_db, d)


def test_validation_rejects_bad_answer_letter(raw_db, tmp_path):
    import json
    d = make_pack(tmp_path / 'packs3', pack_id='bad-q')
    bad = {'id': 'z1', 'module': 'mod-a', 'type': 'single_choice',
           'stem': 's', 'options': ['a', 'b'], 'answer': 'C'}
    with (d / 'data' / 'questions.jsonl').open('w', encoding='utf-8') as fh:
        fh.write(json.dumps(bad, ensure_ascii=False) + '\n')
    with pytest.raises(PackValidationError):
        install_pack(raw_db, d)
