"""通用 JSONL 题库导入器：任何开源社区的题目数据，转成内容包即可注入。

输入：一个 JSONL 文件（每行一题，字段与框架题目协议一致：
      id/module/type/stem/options/answer/explanation/difficulty/...）
      + 必填 modules（可由数据自动归纳）。
输出：标准内容包目录，走统一安装通道。
"""
import json
from collections import OrderedDict
from pathlib import Path

import yaml

from ..contentpack.loader import install_pack, QUESTION_TYPES


def build_pack_dir(jsonl_path: Path, out_root: Path, pack_id: str, pack_name: str,
                   module_names: dict[str, str] | None = None) -> Path:
    jsonl_path = Path(jsonl_path)
    questions = []
    modules: 'OrderedDict[str, str]' = OrderedDict()
    with jsonl_path.open(encoding='utf-8') as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            q = json.loads(line)
            for field in ('id', 'module', 'type', 'stem', 'answer'):
                if not q.get(field):
                    raise ValueError(f'第 {line_no} 行缺少字段 {field}')
            if q['type'] not in QUESTION_TYPES:
                raise ValueError(f'第 {line_no} 行非法题型 {q["type"]}')
            mid = str(q['module'])
            if mid not in modules:
                modules[mid] = (module_names or {}).get(mid, mid)
            q.setdefault('options', [])
            q.setdefault('explanation', '')
            q.setdefault('difficulty', 3)
            q.setdefault('estimated_seconds', 60)
            q.setdefault('nodes', [])
            q.setdefault('tags', [])
            questions.append(q)

    if not questions:
        raise ValueError('JSONL 中没有有效题目')

    pack_dir = Path(out_root) / pack_id
    (pack_dir / 'data').mkdir(parents=True, exist_ok=True)
    module_list = [{'id': mid, 'name': name} for mid, name in modules.items()]
    # 无外部知识树时自动生成模块级知识树；题目悬空的 nodes 绑定回退到模块节点
    module_ids = {m['id'] for m in module_list}
    tree = [{'code': m['id'], 'name': m['name'], 'module_id': m['id'],
             'description': '', 'children': []} for m in module_list]
    for q in questions:
        q['nodes'] = [c for c in (q.get('nodes') or []) if c in module_ids] or [q['module']]
    manifest = {
        'id': pack_id, 'name': pack_name, 'version': '1.0.0',
        'description': f'由 JSONL 题库导入: {jsonl_path.name}（{len(questions)}题）',
        'modules': module_list,
        'source': {'kind': 'jsonl', 'path': str(jsonl_path)},
    }
    (pack_dir / 'pack.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (pack_dir / 'data' / 'knowledge_tree.json').write_text(
        json.dumps(tree, ensure_ascii=False, indent=1), encoding='utf-8')
    with (pack_dir / 'data' / 'questions.jsonl').open('w', encoding='utf-8') as fh:
        for q in questions:
            fh.write(json.dumps(q, ensure_ascii=False) + '\n')
    return pack_dir


def import_jsonl(db, jsonl_path: Path, out_root: Path, pack_id: str, pack_name: str,
                 module_names: dict[str, str] | None = None) -> dict:
    pack_dir = build_pack_dir(Path(jsonl_path), Path(out_root), pack_id, pack_name, module_names)
    result = install_pack(db, pack_dir, force=True)
    result['pack_dir'] = str(pack_dir)
    return result
