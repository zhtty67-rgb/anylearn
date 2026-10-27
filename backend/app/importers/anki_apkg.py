"""Anki 共享牌组（.apkg）导入器 —— 开源社区学习资料的第一入口。

AnkiWeb shared decks 有数万个开放牌组。.apkg 是 zip 包，内含 collection.anki2
（SQLite）。兼容新旧两种 schema：
- 旧版：col 表内 models/decks JSON
- 新版（2.1.50+）：notetypes/templates/decks 独立表

映射规则：
- 牌组 "父::子" → 一级为模块，完整路径为知识节点
- Basic Q/A 卡 → self_rate 题型（自评 again/hard/good/easy）
- Cloze 卡 → cloze 题型（{{c1::答案}} 挖空为 ____）
- 不解析媒体文件（图片/音频跳过，纯文本学习）
"""
import html as html_lib
import json
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..contentpack.loader import install_pack


def _strip_html(text: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', text or '', flags=re.I)
    text = re.sub(r'</(div|p|li)>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = html_lib.unescape(text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _slug(name: str) -> str:
    s = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', name or '').strip('-').lower()
    return s or 'deck'


CLOZE_RE = re.compile(r'\{\{c\d+::(.*?)(?:::.*)?\}\}', re.S)


def _cloze_to_question(front: str) -> tuple[str, str | None]:
    """把 Anki cloze 模板转为（挖空题面, 第一个空答案）。无可挖空则 (原文, None)。"""
    matches = CLOZE_RE.findall(front)
    if not matches:
        return _strip_html(front), None
    stem = CLOZE_RE.sub('____', front)
    return _strip_html(stem), _strip_html(matches[0])


def _open_collection(src: Path) -> sqlite3.Connection:
    """打开 .apkg（zip）或裸 .anki2 收藏库文件。裸文件以只读方式打开，不锁用户的 Anki。"""
    src = Path(src)
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            member = next(n for n in zf.namelist() if n.endswith('.anki2'))
            with tempfile.NamedTemporaryFile(suffix='.anki2', delete=False) as tmp:
                tmp.write(zf.read(member))
                path = tmp.name
        con = sqlite3.connect(path)
    else:
        con = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    return con


def _safe_config(raw) -> dict:
    """新版 Anki 的 notetypes.config 可能是 JSON 文本或私有二进制；解不出按空配置处理。"""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except UnicodeDecodeError:
            return {}
    try:
        return json.loads(raw or '{}')
    except (json.JSONDecodeError, TypeError):
        return {}


def _load_anki_schema(con: sqlite3.Connection):
    """返回 (deck_id→name, note_type_id→{name,type}, notes, note_id→deck_id)。"""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'notetypes' in tables:  # 新版 schema
        # 新版 deck 名以 \x1f 作为层级分隔符
        decks = {r['id']: r['name'].replace('\x1f', '::') for r in con.execute('SELECT id, name FROM decks')}
        notetypes = {r['id']: {'name': r['name'], 'type': _safe_config(r['config']).get('type', 0)}
                     for r in con.execute('SELECT id, name, config FROM notetypes')}
        notes = [{'id': r['id'], 'flds': r['flds'].split('\x1f'), 'mid': r['mid']}
                 for r in con.execute('SELECT id, mid, flds FROM notes')]
    else:  # 旧版 schema
        col = con.execute('SELECT models, decks FROM col').fetchone()
        models = {int(k): v for k, v in json.loads(col['models']).items()}
        decks = {int(k): v['name'] for k, v in json.loads(col['decks']).items()}
        notetypes = {mid: {'name': m['name'], 'type': m.get('type', 0)} for mid, m in models.items()}
        notes = [{'id': r['id'], 'flds': r['flds'].split('\x1f'), 'mid': r['mid']}
                 for r in con.execute('SELECT id, mid, flds FROM notes')]
    # 卡片 → 牌组归属
    card_deck = {r['nid']: r['did'] for r in con.execute('SELECT nid, did FROM cards')}
    return decks, notetypes, notes, card_deck


def build_pack_dir(apkg_path: Path, out_root: Path, pack_id: str | None = None,
                   pack_name: str | None = None) -> Path:
    """把 .apkg / .anki2 解析为标准内容包目录（pack.yaml + tree + questions.jsonl）。"""
    apkg_path = Path(apkg_path)
    con = _open_collection(apkg_path)
    try:
        decks, notetypes, notes, card_deck = _load_anki_schema(con)
    finally:
        con.close()

    pack_id = pack_id or _slug(pack_name or apkg_path.stem)
    if not re.fullmatch(r'[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff_-]*', pack_id):
        pack_id = 'anki-pack'
    pack_name = pack_name or decks.get(1, apkg_path.stem) or apkg_path.stem

    questions = []
    node_map: dict[str, dict] = {}   # full deck path → node
    modules: dict[str, str] = {}     # module_id → name
    default_deck = next((did for did, name in decks.items() if name in ('Default', '默认')), None)

    for note in notes:
        deck_id = card_deck.get(note['id'], default_deck)
        deck_name = decks.get(deck_id) or decks.get(1) or 'Default'
        parts = [p.strip() for p in deck_name.split('::') if p.strip() and p.strip() != 'Default']
        if not parts:
            parts = [pack_name or '卡片']
        module_name = parts[0]
        module_id = _slug(module_name)
        modules.setdefault(module_id, module_name)
        node_path = '::'.join(parts)
        node = node_map.setdefault(node_path, {
            'module_id': module_id, 'module_name': module_name,
            'codes': [_slug(p) for p in parts], 'names': parts, 'questions': [],
        })
        nt = notetypes.get(note['mid'], {'name': 'Basic', 'type': 0})
        front = note['flds'][0] if note['flds'] else ''
        back = note['flds'][1] if len(note['flds']) > 1 else ''
        explanation = _strip_html(back)
        base_id = f'{pack_id}:n{note["id"]}'
        if nt.get('type') == 1 or '{{c' in front:  # cloze（按笔记内容探测，兼容config不可读）
            stem, answer = _cloze_to_question(front)
            if answer:
                node['questions'].append({
                    'id': base_id, 'module': module_id, 'type': 'cloze',
                    'stem': stem, 'answer': answer, 'explanation': explanation,
                    'difficulty': 3, 'estimated_seconds': 60,
                    'tags': [nt['name']], 'nodes': [],
                })
                continue
            # cloze 无可挖空 → 退化为自评卡
        node['questions'].append({
            'id': base_id, 'module': module_id, 'type': 'self_rate',
            'stem': _strip_html(front), 'answer': 'good',
            'explanation': explanation, 'difficulty': 3, 'estimated_seconds': 45,
            'tags': [nt['name']], 'nodes': [],
        })

    # 组装包目录
    pack_dir = Path(out_root) / pack_id
    (pack_dir / 'data').mkdir(parents=True, exist_ok=True)
    (pack_dir / 'assets').mkdir(exist_ok=True)
    module_list = [{'id': mid, 'name': name} for mid, name in modules.items()]

    # 知识树：模块根 > 牌组路径（去掉与模块重复的首级后逐级嵌套）
    tree_acc: dict[str, dict] = {m['id']: {'children': [], 'question_ids': []} for m in module_list}
    for node in node_map.values():
        codes, names = node['codes'], node['names']
        qids = [q['id'] for q in node['questions']]
        if len(codes) == 1:
            # 牌组本身就是模块顶级：题目直接挂在模块根上
            tree_acc[node['module_id']]['question_ids'].extend(qids)
        else:
            tree_acc[node['module_id']]['children'].append(_nest_range(codes, names, qids, 1))
    tree = []
    for m in module_list:
        acc = tree_acc[m['id']]
        tree.append({'code': m['id'], 'name': m['name'], 'module_id': m['id'],
                     'description': '', 'children': merge_children(acc['children']),
                     'question_ids': acc['question_ids']})

    all_questions = []
    for node in node_map.values():
        all_questions.extend(node['questions'])

    manifest = {
        'id': pack_id, 'name': pack_name, 'version': '1.0.0',
        'description': f'由 Anki 牌组导入: {apkg_path.name}',
        'modules': module_list,
        'source': {'kind': 'anki-apkg', 'path': str(apkg_path)},
    }
    (pack_dir / 'pack.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (pack_dir / 'data' / 'knowledge_tree.json').write_text(
        json.dumps(tree, ensure_ascii=False, indent=1), encoding='utf-8')
    with (pack_dir / 'data' / 'questions.jsonl').open('w', encoding='utf-8') as fh:
        for q in all_questions:
            fh.write(json.dumps(q, ensure_ascii=False) + '\n')
    return pack_dir


def _nest_range(codes: list[str], names: list[str], question_ids: list[str], start: int) -> dict:
    """把牌组路径 codes[start:] 嵌套为树节点，题目挂最深层。"""
    def rec(i: int) -> dict:
        n = {'code': '-'.join(codes[: i + 1]), 'name': names[i], 'description': '',
             'children': [], 'question_ids': []}
        if i + 1 < len(codes):
            n['children'].append(rec(i + 1))
        else:
            n['question_ids'] = question_ids
        return n

    return rec(start)


def merge_children(nodes: list[dict]) -> list[dict]:
    """合并同名同级节点。"""
    merged: dict[str, dict] = {}
    for n in nodes:
        if n['code'] in merged:
            merged[n['code']]['children'].extend(n.get('children') or [])
            merged[n['code']]['question_ids'].extend(n.get('question_ids') or [])
        else:
            merged[n['code']] = n
    for n in merged.values():
        n['children'] = merge_children(n.get('children') or [])
    return list(merged.values())


def import_apkg(db, apkg_path: Path, out_root: Path, pack_id: str | None = None,
                pack_name: str | None = None) -> dict:
    """导入 .apkg：先转为标准内容包目录，再走统一安装通道。"""
    pack_dir = build_pack_dir(Path(apkg_path), Path(out_root), pack_id=pack_id, pack_name=pack_name)
    result = install_pack(db, pack_dir, force=True)
    result['pack_dir'] = str(pack_dir)
    return result
