"""开源社区导入器：Anki .apkg（新旧schema）与通用 JSONL。"""
import json
import sqlite3
import zipfile

import pytest

from app.importers.anki_apkg import import_apkg
from app.importers.jsonl_import import import_jsonl
from tests.conftest import QUESTIONS


def _build_legacy_apkg(path, notes_spec):
    """构造旧版 schema 的 .apkg：col 表内嵌 models/decks JSON。"""
    con = sqlite3.connect(path)
    con.executescript('''
        CREATE TABLE col (models TEXT, decks TEXT);
        CREATE TABLE notes (id INTEGER, mid INTEGER, flds TEXT);
        CREATE TABLE cards (nid INTEGER, did INTEGER);
    ''')
    models = {
        '1700000000001': {'name': 'Basic', 'type': 0, 'flds': [{'name': 'Front'}, {'name': 'Back'}]},
        '1700000000002': {'name': 'Cloze', 'type': 1, 'flds': [{'name': 'Text'}, {'name': 'Back Extra'}]},
    }
    decks = {
        '1': {'name': 'Default'},
        '1700000000101': {'name': '日语::N5词汇'},
        '1700000000102': {'name': '日语::N5语法'},
    }
    con.execute('INSERT INTO col VALUES (?,?)', (json.dumps(models), json.dumps(decks)))
    for nid, (mid, front, back, did) in enumerate(notes_spec, start=1001):
        con.execute('INSERT INTO notes VALUES (?,?,?)', (nid, mid, '\x1f'.join([front, back])))
        con.execute('INSERT INTO cards VALUES (?,?)', (nid, did))
    con.commit()
    con.close()
    apkg = str(path) + '.apkg'
    with zipfile.ZipFile(apkg, 'w') as zf:
        zf.write(path, 'collection.anki2')
    return apkg


def test_import_legacy_apkg(db, tmp_path):
    src = tmp_path / 'legacy.anki2'
    apkg = _build_legacy_apkg(src, [
        (1700000000001, 'リーダー　领导者', 'leader；领头人', 1700000000101),
        (1700000000002, '彼は{{c1::先生}}です', '先生 = 老师', 1700000000102),
        (1700000000002, ' plain no cloze ', 'fallback', 1700000000102),
    ])
    result = import_apkg(db, apkg, tmp_path / 'content-packs',
                         pack_id='jp-n5', pack_name='日语N5')
    assert result['status'] == 'installed'
    assert result['questions'] == 3
    # 模块来自牌组一级：日语（两个牌组合并为一个模块）
    modules = {r['id']: r['name'] for r in db.execute('SELECT * FROM modules')}
    assert '日语' in modules
    # cloze 卡被转为 cloze 题型，挖空为答案
    cloze_q = db.execute("SELECT * FROM questions WHERE type='cloze'").fetchone()
    assert cloze_q['answer'] == '先生'
    assert '____' in cloze_q['stem']
    # basic 卡为自评卡
    self_q = db.execute("SELECT * FROM questions WHERE type='self_rate'").fetchone()
    assert 'リーダー' in self_q['stem']
    # 知识树存在且绑定题目
    assert db.execute('SELECT COUNT(*) c FROM question_node_map').fetchone()['c'] == 3


def test_import_bare_anki2_collection(db, tmp_path):
    """裸 collection.anki2（本机Anki收藏库）以只读方式直接导入。"""
    src = tmp_path / 'collection.anki2'
    _build_legacy_apkg(src, [
        (1700000000001, 'リーダー 领导者', 'leader', 1700000000101),
    ])
    result = import_apkg(db, src, tmp_path / 'content-packs', pack_id='my-anki', pack_name='本机收藏')
    assert result['status'] == 'installed' and result['questions'] == 1
    assert db.execute("SELECT COUNT(*) c FROM questions WHERE pack_id='my-anki'").fetchone()['c'] == 1


def test_import_jsonl(db, tmp_path):
    src = tmp_path / 'bank.jsonl'
    with src.open('w', encoding='utf-8') as fh:
        for q in QUESTIONS:
            fh.write(json.dumps(q, ensure_ascii=False) + '\n')
    result = import_jsonl(db, src, tmp_path / 'content-packs',
                          pack_id='custom-bank', pack_name='自定义题库')
    assert result['status'] == 'installed'
    assert db.execute("SELECT COUNT(*) c FROM questions WHERE pack_id='custom-bank'").fetchone()['c'] == 5


def test_import_jsonl_rejects_bad_type(db, tmp_path):
    src = tmp_path / 'bad.jsonl'
    src.write_text(json.dumps({'id': 'x', 'module': 'm', 'type': 'essay',
                               'stem': 's', 'answer': 'a'}) + '\n', encoding='utf-8')
    with pytest.raises(ValueError):
        import_jsonl(db, src, tmp_path / 'content-packs', 'bad', '坏题库')
