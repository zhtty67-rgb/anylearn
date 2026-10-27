#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把本机《英语词义分类数据库（大学版）》转换成 AnyLearn 内容包。

输入：<用户主目录>/英语词义库/英语词义分类数据库（大学版）  (Obsidian 语义分类词库)
      可用环境变量 VOCAB_SRC 覆盖具体路径。
输出：content-packs/english-vocab/（pack.yaml + knowledge_tree.json + questions.jsonl）

每个词条生成：
  - wm    单词→释义 单选题
  - mw    释义→单词 单选题
  - cloze 例句挖空填词（有含该词的例句时）
知识树：领域(模块) > 子类(章节) > 词组文件(考点)
干扰项从同章节词池确定性抽取，重复构建结果稳定。
"""
import json
import os
import random
import re
import sys
from hashlib import sha256
from pathlib import Path

import yaml

SRC = Path(os.environ.get('VOCAB_SRC', Path.home() / '英语词义库' / '英语词义分类数据库（大学版）'))
OUT_ROOT = Path(__file__).resolve().parents[1] / 'content-packs'
PACK_ID = 'english-vocab'

VOCAB_RE = re.compile(
    r'<span class="vocabulary">\s*\*{0,2}(.*?)\*{0,2}\s*</span>(.*?)(?=<span class="vocabulary">|$)', re.S)
DEF_RE = re.compile(r'<span class="definition">(.*?)</span>', re.S)
TAG_RE = re.compile(r'<[^>]+>')
IPA_RE = re.compile(r'^\s*[\[［]([^\]］]+)[\]］]')
GROUP_NUM_RE = re.compile(r'^\d+[._\s]*')
LETTERS = 'ABCD'


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', TAG_RE.sub('', text or '')).strip()


def word_key(word: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', word.lower()).strip('-')


def short_meaning(defs: list[str], limit: int = 48) -> str:
    if not defs:
        return ''
    m = clean(defs[0]).rstrip('：:')
    return (m[: limit - 1] + '…') if len(m) > limit else m


def first_example(body_plain: str, word: str) -> str | None:
    """返回第一个包含该词（整词匹配）的例句片段。"""
    pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.I)
    for frag in re.split(r'\s*/\s*|\n', body_plain):
        frag = clean(frag)
        if 12 <= len(frag) <= 140 and pattern.search(frag):
            return frag
    return None


def render_explanation(word, ipa, defs, plain) -> str:
    lines = [f'**{word}**' + (f' [{ipa}]' if ipa else '')]
    for d in defs:
        c = clean(d)
        if c:
            lines.append(f'- {c}')
    tail = clean(plain)[:400]
    if tail:
        lines.append(f'\n例句：{tail}')
    return '\n'.join(lines)[:800]


def parse_file(path: Path) -> list[dict]:
    text = path.read_text(encoding='utf-8', errors='ignore')
    entries = []
    for m in VOCAB_RE.finditer(text):
        word = clean(m.group(1))
        body = m.group(2)
        if not word or not re.search(r'[a-zA-Z]', word):
            continue
        defs = DEF_RE.findall(body)
        plain = TAG_RE.sub(' ', body)
        ipa_m = IPA_RE.match(plain)
        entries.append({
            'word': word,
            'ipa': ipa_m.group(1).strip() if ipa_m else '',
            'meaning': short_meaning(defs),
            'body_plain': clean(plain),
            'explanation': render_explanation(word, ipa_m.group(1).strip() if ipa_m else '', defs, plain),
        })
    return entries


def slug(name: str) -> str:
    return re.sub(r'[\s、，,·/\\:：()（）]+', '-', name.strip()).strip('-') or 'x'


def name_of(p: Path) -> str:
    stem = p.stem if p.suffix else p.name
    return GROUP_NUM_RE.sub('', stem).strip() or p.name


def pick_distractors(pool: list[dict], correct_word: str, field: str, n: int = 3) -> list[str]:
    rng = random.Random(int(sha256(correct_word.encode()).hexdigest()[:12], 16))
    candidates = [p[field] for p in pool if p['word'].lower() != correct_word.lower() and p[field]]
    rng.shuffle(candidates)
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) == n:
            break
    return out


def answer_slot(word: str, kind: str) -> int:
    return int(sha256(f'{word}:{kind}'.encode()).hexdigest(), 16) % 4


def main():
    if not SRC.is_dir():
        sys.exit(f'词库不存在: {SRC}')
    pack_dir = OUT_ROOT / PACK_ID
    (pack_dir / 'data').mkdir(parents=True, exist_ok=True)

    # ---------- 第一遍：解析全部词组文件 ----------
    parsed = []      # (domain_name, chapter_name, group_name, entries)
    for dom in sorted([d for d in SRC.iterdir()
                       if d.is_dir() and d.name[0].isdigit()
                       and not d.name.startswith('00') and not d.name.startswith('0本')
                       and '目录' not in d.name],
                      key=lambda d: d.name):
        dom_name = name_of(dom)
        chapters = sorted([c for c in dom.iterdir()
                           if c.is_dir() and c.name[0].isdigit()
                           and not c.name.startswith('00') and '目录' not in c.name],
                          key=lambda c: c.name) or [dom]
        for chap in chapters:
            chap_name = name_of(chap) if chap != dom else dom_name
            for f in sorted(chap.glob('*.md')):
                if not f.stem.startswith('00') and '目录' not in f.name:
                    entries = parse_file(f)
                    if entries:
                        parsed.append((dom_name, chap_name, name_of(f), entries))

    chapter_pools: dict[tuple, list[dict]] = {}
    for dom_name, chap_name, _, entries in parsed:
        chapter_pools.setdefault((dom_name, chap_name), []).extend(
            {'word': e['word'], 'meaning': e['meaning']} for e in entries)
    global_pool = [p for pool in chapter_pools.values() for p in pool]

    # ---------- 第二遍：生成题目 + 知识树 ----------
    used_ids = set()
    stats = {'groups': len(parsed), 'entries': 0, 'questions': 0, 'cloze': 0}
    module_ids: dict[str, str] = {}
    tree_by_module: dict[str, dict] = {}

    def emit(q) -> str:
        base, qid, n = q['id'], q['id'], 2
        while qid in used_ids:
            qid = f'{base}-{n}'
            n += 1
        used_ids.add(qid)
        q['id'] = qid
        qfh.write(json.dumps(q, ensure_ascii=False) + '\n')
        stats['questions'] += 1
        return qid

    qfh = (pack_dir / 'data' / 'questions.jsonl').open('w', encoding='utf-8')
    try:
        for dom_name, chap_name, group_name, entries in parsed:
            mod_id = slug(dom_name)
            if mod_id in module_ids and module_ids[mod_id] != dom_name:
                mod_id = f'{mod_id}-{len(module_ids)}'
            module_ids.setdefault(mod_id, dom_name)
            mod = tree_by_module.setdefault(mod_id, {'name': dom_name, 'chapters': {}})
            chap_rec = mod['chapters'].setdefault(
                chap_name, {'name': chap_name, 'code': f'{mod_id}-{slug(chap_name)}', 'groups': []})
            pool = chapter_pools.get((dom_name, chap_name)) or global_pool

            node_code = f"{chap_rec['code']}-{slug(group_name)}"
            if node_code in {g['code'] for g in chap_rec['groups']}:
                node_code += f'-{len(chap_rec["groups"])}'
            qids = []

            for e in entries:
                stats['entries'] += 1
                w, meaning = e['word'], e['meaning']
                wk = word_key(w)
                common = {'module': mod_id, 'nodes': [node_code],
                          'tags': [dom_name, chap_name], 'explanation': e['explanation']}

                if meaning and len(pick_distractors(pool, w, 'meaning')) == 3:
                    slot = answer_slot(w, 'wm')
                    options = pick_distractors(pool, w, 'meaning')
                    options.insert(slot, meaning)
                    qids.append(emit({
                        'id': f'ev-{wk}-wm', 'type': 'single_choice',
                        'stem': f"单词 {w}" + (f" [{e['ipa']}]" if e['ipa'] else '') + ' 的含义是？',
                        'options': options, 'answer': LETTERS[slot],
                        'difficulty': 2, 'estimated_seconds': 30, **common}))

                if meaning and len(pick_distractors(pool, w, 'word')) == 3:
                    slot = answer_slot(w, 'mw')
                    options = pick_distractors(pool, w, 'word')
                    options.insert(slot, w)
                    qids.append(emit({
                        'id': f'ev-{wk}-mw', 'type': 'single_choice',
                        'stem': f'表示「{meaning}」的英文单词是？',
                        'options': options, 'answer': LETTERS[slot],
                        'difficulty': 2, 'estimated_seconds': 30, **common}))

                ex = first_example(e['body_plain'], w)
                if ex:
                    stem = re.sub(r'\b' + re.escape(w) + r'\b', '____', ex, count=1, flags=re.I)
                    qids.append(emit({
                        'id': f'ev-{wk}-cz', 'type': 'cloze',
                        'stem': f'填空：{stem}', 'answer': w,
                        'difficulty': 3, 'estimated_seconds': 45, **common}))
                    stats['cloze'] += 1

            chap_rec['groups'].append({'code': node_code, 'name': group_name, 'question_ids': qids})
    finally:
        qfh.close()

    tree = [{'code': mid, 'name': rec['name'], 'module_id': mid, 'description': '',
             'children': [{'code': c['code'], 'name': c['name'], 'description': '',
                           'children': [{'code': g['code'], 'name': g['name'],
                                         'question_ids': g['question_ids']} for g in c['groups']]}
                          for c in rec['chapters'].values()]}
            for mid, rec in tree_by_module.items()]
    manifest = {
        'id': PACK_ID, 'name': '英语词汇 · 语义分类', 'version': '1.0.0',
        'description': '基于本机《英语词义分类数据库（大学版）》：41个语义领域、按词组分类的双向词汇+例句填空训练。',
        'modules': [{'id': mid, 'name': name} for mid, name in module_ids.items()],
        'theme': {'primary_color': '#296044', 'icon': 'book'},
        'ai': {'teacher_persona': '你是一位中英双语词汇教师，擅长用语义场（同领域词族）讲解单词辨析，'
                                  '鼓励学生通过例句和近义对比记忆单词。'},
        'grading': {'mode': 'objective'},
        'source': {'kind': 'local-corpus', 'path': str(SRC)},
    }
    (pack_dir / 'pack.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (pack_dir / 'data' / 'knowledge_tree.json').write_text(
        json.dumps(tree, ensure_ascii=False), encoding='utf-8')

    print(f"词组文件 {stats['groups']}，词条 {stats['entries']}，"
          f"题目 {stats['questions']}（其中填空 {stats['cloze']}），模块 {len(module_ids)}")
    print(f'输出: {pack_dir}')


if __name__ == '__main__':
    main()
