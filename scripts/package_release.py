#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打包 AnyLearn 发布包（脱敏 + 自检）。

沿用公考 Learning OS 的发布原则：
1. 密钥清除：model_config.toml / 任何配置里的 api_key、token、password 置空；
   源码与文档中不得残留真实密钥。
2. 个人数据清除：数据库保留内容包与知识树等产品数据，清空全部学习记录
   （作答、复习、掌握度、AI 对话），并 VACUUM。
3. 排除本机与临时产物：.venv、.cache（原始资料缓存）、release、data/anylearn.db
   （改以脱敏库放入）、日志、__pycache__、.pytest_cache。
4. 排除未经确认的第三方内容包（默认：ai-learning-framework）。
5. 自检：包内不得出现真实密钥；脱敏库个人表必须为空；不得含本机绝对路径
   （Windows 盘符路径、用户目录）；zip 内文件清单与统计。

用法：
  python scripts/package_release.py                # 打包（含 zip）
  python scripts/package_release.py --no-zip       # 只出目录
  python scripts/package_release.py --with-pack ai-learning-framework  # 显式纳入
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = time.strftime('%Y%m%d-%H%M')
RELEASE = ROOT / 'release'
PKG_NAME = f'anylearn-{STAMP}'
PKG_DIR = RELEASE / PKG_NAME
ZIP_PATH = RELEASE / f'{PKG_NAME}.zip'

# 个人学习数据表（清空行、保留结构）。顺序：先子表后父表，满足外键约束。
PERSONAL_TABLES = [
    'ai_conversations',
    'review_events', 'review_cards',
    'mastery_evidence', 'mastery_state',
    'attempts', 'session_questions', 'quiz_sessions',
]

# 默认排除的内容包：
#  - ai-learning-framework：非本仓库产出的第三方草案
#  - my-anki：来自个人 Anki 收藏，属于个人数据，不随发布包外发
DEFAULT_EXCLUDED_PACKS = {'ai-learning-framework', 'my-anki'}

EXCLUDE_DIRS = {
    '.venv', 'venv', '__pycache__', '.pytest_cache', '.git',
    'release', '.cache', 'node_modules', 'test-results', 'pytest-of-86155',
}
EXCLUDE_FILES = {
    'anylearn.db', 'server.log', 'tmp_pytest.log', 'ceval_tree.json', 'aitree.json',
    '.DS_Store', 'Thumbs.db',
}
EXCLUDE_SUFFIXES = {'.pyc', '.pyo', '.log', '.db-wal', '.db-shm'}

# 密钥检测：键名 + 长字符串值
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[=:]\s*["\']?([A-Za-z0-9_\-\.]{16,})'),
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
]
# 本机绝对路径检测（发布物不应绑定谁的机器）
ABS_PATH_PATTERNS = [
    re.compile(r'[A-Za-z]:\\\\'),          # 双反斜杠
    re.compile(r'(?<![A-Za-z0-9_])[A-Za-z]:\\[A-Za-z\u4e00-\u9fff]'),  # 盘符 + 中文/字母目录
    re.compile(r'C:/Users/'),
]


def log(msg: str) -> None:
    print(f'[package] {msg}', flush=True)


def should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    return path.suffix.lower() in EXCLUDE_SUFFIXES


def copy_tree(src: Path, dst: Path, *, excluded_packs: set[str]) -> None:
    for item in src.rglob('*'):
        rel = item.relative_to(src)
        if should_exclude(item):
            continue
        # 内容包过滤
        if rel.parts[:1] == ('content-packs',) and len(rel.parts) > 1:
            if rel.parts[1] in excluded_packs:
                continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def sanitize_model_config(pkg: Path) -> list[str]:
    """清除 model_config.toml 中的 api_key / base_url，返回改动说明。"""
    changed = []
    for cfg in pkg.rglob('model_config.toml'):
        text = cfg.read_text(encoding='utf-8')
        new = re.sub(r'(?im)^(\s*(api_key|base_url)\s*=\s*)["\']?[^"\'\n]*["\']?',
                     r'\1""', text)
        if new != text:
            cfg.write_text(new, encoding='utf-8')
            changed.append(str(cfg.relative_to(pkg)))
    return changed


def build_sanitized_db(pkg: Path, excluded_packs: set[str]) -> Path:
    """复制数据库到包内，清空个人学习数据与被排除的内容包。"""
    src = ROOT / 'data' / 'anylearn.db'
    dst = pkg / 'data' / 'anylearn.db'
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        log('源数据库不存在，跳过（首次运行会自行创建）')
        return dst
    shutil.copy2(src, dst)
    con = sqlite3.connect(dst)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cleared = []
        for table in PERSONAL_TABLES:
            if table in existing:
                con.execute(f'DELETE FROM {table}')
                cleared.append(table)
        # ai_conversations 为自增主键，重置序列
        if 'ai_conversations' in existing:
            con.execute("DELETE FROM sqlite_sequence WHERE name='ai_conversations'")
        con.commit()

        # 删除被排除的内容包（按依赖顺序）
        removed = []
        for pack_id in sorted(excluded_packs):
            if not con.execute('SELECT 1 FROM packs WHERE id=?', (pack_id,)).fetchone():
                continue
            con.execute(
                'DELETE FROM question_node_map WHERE question_id IN '
                '(SELECT id FROM questions WHERE pack_id=?)', (pack_id,))
            con.execute(
                'DELETE FROM mastery_state WHERE knowledge_node_id IN '
                '(SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
            con.execute(
                'DELETE FROM mastery_evidence WHERE knowledge_node_id IN '
                '(SELECT id FROM knowledge_nodes WHERE pack_id=?)', (pack_id,))
            con.execute('DELETE FROM review_events WHERE question_id IN '
                        '(SELECT id FROM questions WHERE pack_id=?)', (pack_id,))
            con.execute('DELETE FROM review_cards WHERE question_id IN '
                        '(SELECT id FROM questions WHERE pack_id=?)', (pack_id,))
            con.execute('DELETE FROM questions WHERE pack_id=?', (pack_id,))
            con.execute('DELETE FROM knowledge_nodes WHERE pack_id=?', (pack_id,))
            con.execute('DELETE FROM modules WHERE pack_id=?', (pack_id,))
            con.execute('DELETE FROM packs WHERE id=?', (pack_id,))
            removed.append(pack_id)
        con.commit()
        con.execute('VACUUM')
        log(f'个人数据已清空: {", ".join(cleared)}')
        if removed:
            log(f'已移除被排除内容包的数据: {", ".join(removed)}')
    finally:
        con.close()
    return dst


def verify_db(pkg: Path) -> dict:
    db = pkg / 'data' / 'anylearn.db'
    if not db.is_file():
        return {'skipped': True}
    con = sqlite3.connect(db)
    try:
        stats = {'packs': {}, 'personal_rows': {}}
        for pid, name, qn in con.execute(
                'SELECT p.id, p.name, (SELECT COUNT(*) FROM questions q WHERE q.pack_id=p.id) FROM packs p'):
            stats['packs'][pid] = {'name': name, 'questions': qn}
        for table in PERSONAL_TABLES:
            try:
                stats['personal_rows'][table] = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            except sqlite3.OperationalError:
                continue
        return stats
    finally:
        con.close()


def scan_secrets(pkg: Path) -> list[str]:
    """扫描包内文本文件中的密钥与本机绝对路径。"""
    issues = []
    text_suffixes = {'.py', '.toml', '.yaml', '.yml', '.json', '.jsonl', '.md', '.txt',
                     '.js', '.css', '.html', '.sql', '.ps1', '.bat', '.cfg', '.ini'}
    for f in pkg.rglob('*'):
        if not f.is_file() or f.suffix.lower() not in text_suffixes:
            continue
        # 题库/知识树可能很大，只在大文件前 200KB 内扫描绝对路径（内容本身不含路径）
        try:
            data = f.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        rel = f.relative_to(pkg)
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(data):
                issues.append(f'[密钥?] {rel}: {m.group(0)[:80]}')
        if rel.parts[:1] == ('content-packs',):
            continue  # 内容包正文允许出现教材引用等文本
        if rel.name == 'package_release.py':
            continue  # 打包脚本自身包含检测用正则字面量
        for pat in ABS_PATH_PATTERNS:
            m = pat.search(data)
            if m:
                issues.append(f'[本机路径] {rel}: …{data[max(0, m.start()-30):m.start()+50]}…')
                break
    return issues


def make_zip(pkg: Path) -> Path:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(pkg.rglob('*')):
            if f.is_file():
                zf.write(f, f.relative_to(pkg.parent))
    return ZIP_PATH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-zip', action='store_true')
    ap.add_argument('--with-pack', action='append', default=[],
                    help='显式纳入默认排除的内容包（可多次）')
    args = ap.parse_args()

    excluded = DEFAULT_EXCLUDED_PACKS - set(args.with_pack)
    if excluded:
        log(f'排除内容包: {", ".join(sorted(excluded))}（如需纳入用 --with-pack）')

    if PKG_DIR.exists():
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True)

    log('复制工程文件…')
    copy_tree(ROOT, PKG_DIR, excluded_packs=excluded)

    log('脱敏模型配置…')
    for c in sanitize_model_config(PKG_DIR):
        log(f'  已置空密钥/端点: {c}')

    log('生成脱敏数据库…')
    build_sanitized_db(PKG_DIR, excluded)

    log('自检…')
    issues = scan_secrets(PKG_DIR)
    stats = verify_db(PKG_DIR)
    dirty = {k: v for k, v in (stats.get('personal_rows') or {}).items() if v}
    if dirty:
        issues.append(f'[个人数据残留] {dirty}')

    if issues:
        log('!! 自检发现问题：')
        for i in issues[:30]:
            log('   ' + i)
        if len(issues) > 30:
            log(f'   …共 {len(issues)} 项')
    else:
        log('自检通过：无密钥、无本机路径、个人数据为空')

    if stats.get('packs'):
        log('随包内容包：')
        for pid, info in stats['packs'].items():
            log(f"   {pid}: {info['questions']} 题 — {info['name']}")

    manifest = {
        'name': PKG_NAME,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'excluded_packs': sorted(excluded),
        'included_packs': sorted((stats.get('packs') or {}).keys()),
        'self_check': {'passed': not issues, 'issues': issues},
    }
    (PKG_DIR / 'RELEASE_MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    if not args.no_zip:
        z = make_zip(PKG_DIR)
        size = z.stat().st_size / 1024 / 1024
        log(f'打包完成: {z}  ({size:.1f} MB)')
    log(f'目录: {PKG_DIR}')
    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
