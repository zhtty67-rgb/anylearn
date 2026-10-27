"""API 全链路：内容包 → 做题 → 复习 → 知识树 → 概览 → AI → 导入。"""
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import QUESTIONS
from tests.test_importers import _build_legacy_apkg


def make_client(tmp_path, content_root):
    db_path = tmp_path / 'api.db'
    app = create_app(db_path=db_path, content_root=content_root)
    return TestClient(app)


def test_full_api_flow(tmp_path, content_root):
    with make_client(tmp_path, content_root) as client:
        assert client.get('/api/health').json()['status'] == 'ok'

        # 启动时自动安装
        packs = client.get('/api/packs').json()['packs']
        assert [p['id'] for p in packs] == ['demo-pack']
        assert packs[0]['questions'] == 5
        assert packs[0]['theme']['primary_color'] == '#0ea5e9'

        # 概览
        ov = client.get('/api/packs/demo-pack/overview').json()
        assert ov['questions'] == 5 and ov['modules'][0]['name'] == '模块甲'

        # 组题 + 作答
        s = client.post('/api/quiz/sessions',
                        json={'pack_id': 'demo-pack', 'module_ids': ['mod-a'], 'count': 10}).json()
        sid = s['session_id']
        detail = client.get(f'/api/quiz/sessions/{sid}').json()
        assert len(detail['questions']) == 2
        r = client.post(f'/api/quiz/sessions/{sid}/answers',
                        json={'question_id': 'q1', 'answer': 'A', 'confidence': 0.9,
                              'elapsed_ms': 3000}).json()
        assert r['correct'] is True
        r2 = client.post(f'/api/quiz/sessions/{sid}/answers',
                         json={'question_id': 'q2', 'answer': None, 'confidence': 0.2,
                               'elapsed_ms': 3000}).json()
        assert r2['correct'] is False and r2['session_finished']

        result = client.get(f'/api/quiz/sessions/{sid}/result').json()
        assert result['total'] == 2 and result['correct'] == 1

        # FSRS：新卡答错也在约1天后到期，当下应无到期项；复习模式会话因此被拒
        due = client.get('/api/review/due', params={'pack_id': 'demo-pack'}).json()
        assert due['count'] == 0
        resp = client.post('/api/quiz/sessions',
                           json={'pack_id': 'demo-pack', 'mode': 'review', 'count': 5})
        assert resp.status_code == 400

        # 知识树
        tree = client.get('/api/packs/demo-pack/tree').json()
        assert len(tree['roots']) == 2
        leaf = tree['roots'][0]['children'][0]['children'][0]
        assert leaf['questions'] >= 1 and leaf['mastery'] is not None

        # AI 教师（mock）
        ai = client.post('/api/ai/teacher', json={
            'pack_id': 'demo-pack', 'mode': 'hint', 'question_id': 'q1',
            'message': '从哪入手'}).json()
        assert ai['mock'] is True
        history = client.get('/api/ai/conversations', params={'pack_id': 'demo-pack'}).json()
        assert len(history['messages']) == 2


def test_api_import_anki_and_jsonl(tmp_path, content_root):
    with make_client(tmp_path, content_root) as client:
        raw = tmp_path / 'legacy.anki2'
        apkg = _build_legacy_apkg(raw, [
            (1700000000001, 'リーダー 领导者', 'leader', 1700000000101),
        ])
        r = client.post('/api/import/anki', json={
            'path': apkg, 'pack_id': 'jp-n5', 'pack_name': '日语N5'}).json()
        assert r['status'] == 'installed'
        packs = {p['id'] for p in client.get('/api/packs').json()['packs']}
        assert {'demo-pack', 'jp-n5'} <= packs

        src = tmp_path / 'bank.jsonl'
        with src.open('w', encoding='utf-8') as fh:
            for q in QUESTIONS:
                fh.write(json.dumps(q, ensure_ascii=False) + '\n')
        r2 = client.post('/api/import/jsonl', json={
            'path': str(src), 'pack_id': 'custom', 'pack_name': '自定义题库'}).json()
        assert r2['status'] == 'installed'


def test_api_validation_errors(tmp_path, content_root):
    with make_client(tmp_path, content_root) as client:
        assert client.post('/api/quiz/sessions',
                           json={'pack_id': 'ghost'}).status_code == 404
        assert client.post('/api/import/anki',
                           json={'path': str(tmp_path / 'nope.apkg')}).status_code == 404
        assert client.post('/api/ai/teacher',
                           json={'pack_id': 'demo-pack', 'mode': 'hack'}).status_code == 400
        assert client.get('/api/packs/ghost/overview').status_code == 404
