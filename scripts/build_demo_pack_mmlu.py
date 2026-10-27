#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成开箱即用的演示内容包 demo-ai-mmlu（MMLU，MIT 许可，可自由分发）。

MMLU: https://huggingface.co/datasets/cais/mmlu  (MIT)
用法：
    python scripts/build_demo_pack_mmlu.py            # 需本地已有 parquet 缓存
    python scripts/build_demo_pack_mmlu.py --fetch    # 自动下载

产物：content-packs/demo-ai-mmlu/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache' / 'mmlu'
OUT = ROOT / 'content-packs' / 'demo-ai-mmlu'
PACK_ID = 'demo-ai-mmlu'
LETTERS = 'ABCD'
BASE = 'https://huggingface.co/datasets/cais/mmlu/resolve/main'

# 学科 → (模块 id, 中文名, 每科取题上限)
SUBJECTS = {
    'machine_learning': ('ml', '机器学习', 112),
    'college_computer_science': ('cs', '计算机科学', 100),
    'computer_security': ('sec', '计算机安全', 100),
    'high_school_computer_science': ('cs-basic', '计算机基础', 100),
    'electrical_engineering': ('ee', '电子工程', 145),
}


def fetch(subject: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f'{subject}.parquet'
    if dst.is_file() and dst.stat().st_size > 1000:
        return dst
    url = f'{BASE}/{subject}/test-00000-of-00001.parquet'
    print(f'  下载 {subject} …')
    with urllib.request.urlopen(url, timeout=120) as r, dst.open('wb') as f:
        f.write(r.read())
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true', help='缺失时自动下载')
    args = ap.parse_args()

    questions, modules, tree = [], [], []
    total = 0
    for subject, (mid, cn, cap) in SUBJECTS.items():
        path = CACHE / f'{subject}.parquet'
        if not path.is_file():
            if not args.fetch:
                print(f'  跳过 {subject}（无缓存，加 --fetch 下载）')
                continue
            path = fetch(subject)
        df = pd.read_parquet(path)
        items = []
        for i, row in df.head(cap).iterrows():
            choices = [str(c) for c in row['choices']]
            if len(choices) != 4:
                continue
            idx = int(row['answer'])
            qid = f'mmlu-{subject.replace("_", "-")}-{i + 1:03d}'
            items.append({
                'id': qid, 'module': mid, 'type': 'single_choice',
                'stem': ' '.join(str(row['question']).split()),
                'options': choices,
                'answer': LETTERS[idx],
                'explanation': f'正确答案：{LETTERS[idx]}. {choices[idx]}',
                'difficulty': 4, 'estimated_seconds': 90,
                'tags': ['MMLU', cn], 'nodes': [],
            })
        if not items:
            continue
        questions.extend(items)
        modules.append({'id': mid, 'name': cn})
        tree.append({
            'code': mid, 'name': cn, 'module_id': mid, 'description': '',
            'children': [{
                'code': f'{mid}-questions', 'name': f'{cn}题目',
                'description': f'MMLU {subject}',
                'question_ids': [q['id'] for q in items],
            }],
        })
        total += len(items)
        print(f'  {cn}: {len(items)} 题')

    if not questions:
        sys.exit('没有可用数据；请先加 --fetch 下载')

    (OUT / 'data').mkdir(parents=True, exist_ok=True)
    with (OUT / 'data' / 'questions.jsonl').open('w', encoding='utf-8') as fh:
        for q in questions:
            fh.write(json.dumps(q, ensure_ascii=False) + '\n')
    (OUT / 'data' / 'knowledge_tree.json').write_text(
        json.dumps(tree, ensure_ascii=False, indent=1), encoding='utf-8')

    manifest = {
        'id': PACK_ID,
        'name': 'MMLU 人工智能与计算机（演示包）',
        'version': '1.0.0',
        'description': f'开箱即用的演示内容包：MMLU 机器学习/计算机学科真题 {total} 题（MIT 许可，可自由分发）。',
        'modules': modules,
        'theme': {'primary_color': '#296044', 'icon': 'cpu'},
        'ai': {'teacher_persona': '你是一位计算机科学讲师，用中英对照讲解英文原题，'
                                  '先解释题干术语，再分析每个选项为何对错。'},
        'grading': {'mode': 'objective'},
        'source': {
            'kind': 'benchmark',
            'url': 'https://huggingface.co/datasets/cais/mmlu',
            'license': 'MIT',
            'citation': 'Measuring Massive Multitask Language Understanding (ICLR 2021)',
        },
    }
    (OUT / 'pack.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f'\n共 {total} 题 → {OUT}')


if __name__ == '__main__':
    main()
