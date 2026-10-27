"""测试夹具：隔离数据库 + 最小演示内容包。绝不触碰正式库。"""
import json
import sys
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import db as db_mod  # noqa: E402

QUESTIONS = [
    {'id': 'q1', 'module': 'mod-a', 'type': 'single_choice',
     'stem': '「王朝」对应的英文单词是？',
     'options': ['dynasty', 'realm', 'empire', 'colony'], 'answer': 'A',
     'explanation': 'dynasty n.[C] 王朝', 'difficulty': 2, 'estimated_seconds': 30,
     'tags': ['词汇'], 'nodes': ['a-1-1']},
    {'id': 'q2', 'module': 'mod-a', 'type': 'cloze',
     'stem': 'The Ming ___ lasted nearly 300 years.（填英文单词：朝代）',
     'answer': 'dynasty', 'explanation': 'the Ming dynasty 明代',
     'difficulty': 3, 'estimated_seconds': 45, 'tags': ['词汇'], 'nodes': ['a-1-1']},
    {'id': 'q3', 'module': 'mod-b', 'type': 'self_rate',
     'stem': '复述：光年是天文学中的距离单位。',
     'answer': 'good', 'explanation': '光年 = 光在真空中一年走过的距离。',
     'difficulty': 2, 'estimated_seconds': 30, 'tags': ['常识'], 'nodes': ['b-1-1']},
    {'id': 'q4', 'module': 'mod-b', 'type': 'single_choice',
     'stem': '1 KB 等于多少字节？',
     'options': ['1000', '1024', '512', '2048'], 'answer': 'B',
     'explanation': '二进制语境下 1KB=1024B。', 'difficulty': 1, 'estimated_seconds': 20,
     'tags': ['计算机'], 'nodes': ['b-1-1']},
    {'id': 'q5', 'module': 'mod-b', 'type': 'short_answer',
     'stem': '请写出“信息”的英文单词。', 'answer': 'information|信息',
     'explanation': 'information n. 信息', 'difficulty': 2, 'estimated_seconds': 30,
     'tags': ['词汇'], 'nodes': ['b-1-1']},
]


def make_pack(root: Path, pack_id: str = 'demo-pack', version: str = '1.0.0',
              with_tree: bool = True, questions=None) -> Path:
    d = root / pack_id
    (d / 'data').mkdir(parents=True, exist_ok=True)
    manifest = {
        'id': pack_id, 'name': '演示学习包', 'version': version,
        'description': '测试用内容包',
        'modules': [{'id': 'mod-a', 'name': '模块甲'}, {'id': 'mod-b', 'name': '模块乙'}],
        'theme': {'primary_color': '#0ea5e9'},
        'ai': {'teacher_persona': '你是一位双语词汇教师。'},
    }
    (d / 'pack.yaml').write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
                                 encoding='utf-8')
    if with_tree:
        tree = [
            {'code': 'mod-a', 'name': '模块甲', 'module_id': 'mod-a', 'children': [
                {'code': 'a-1', 'name': '政治词汇', 'children': [
                    {'code': 'a-1-1', 'name': '朝代王国', 'question_ids': ['q1', 'q2']}]}]},
            {'code': 'mod-b', 'name': '模块乙', 'module_id': 'mod-b', 'children': [
                {'code': 'b-1', 'name': '通识', 'children': [
                    {'code': 'b-1-1', 'name': '杂项', 'question_ids': ['q3', 'q4', 'q5']}]}]},
        ]
        (d / 'data' / 'knowledge_tree.json').write_text(
            json.dumps(tree, ensure_ascii=False), encoding='utf-8')
    with (d / 'data' / 'questions.jsonl').open('w', encoding='utf-8') as fh:
        for q in (questions if questions is not None else QUESTIONS):
            fh.write(json.dumps(q, ensure_ascii=False) + '\n')
    return d


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / 'test.db'
    db_mod.migrate(path)
    return path


@pytest.fixture
def db(db_path):
    with db_mod.connect(db_path) as conn:
        yield conn


@pytest.fixture
def content_root(tmp_path):
    root = tmp_path / 'content-packs'
    root.mkdir()
    make_pack(root)
    return root


@pytest.fixture
def installed_db(db, content_root):
    from app.contentpack.loader import install_pack
    install_pack(db, content_root / 'demo-pack')
    return db
