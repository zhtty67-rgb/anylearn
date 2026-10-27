#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端冒烟：装包态检查 → 组题 → 作答（对/错/空/自评）→ 结算 → 复习到期 → 知识树 → AI教师。"""
import json
import sys
from pathlib import Path

import httpx

BASE = 'http://127.0.0.1:8001'
c = httpx.Client(base_url=BASE, timeout=60, trust_env=False)

fails = []


def check(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f' | {extra}' if extra else ''))
    if not cond:
        fails.append(name)


# 1. 内容包态
packs = c.get('/api/packs').json()['packs']
ev = next(p for p in packs if p['id'] == 'english-vocab')
check('内容包已安装', ev['questions'] == 81199, f"{ev['name']} {ev['questions']}题/{ev['nodes']}节点/{len(ev['modules'])}模块")

ov = c.get('/api/packs/english-vocab/overview').json()
check('总览可读', ov['questions'] == 81199 and len(ov['modules']) == 50)

# 2. 组题（基础领域模块）
s = c.post('/api/quiz/sessions', json={'pack_id': 'english-vocab',
                                       'module_ids': ['基础领域'], 'count': 4}).json()
check('组题成功', s.get('count') == 4, f"session={s.get('session_id','?')[:8]}…")
sid = s['session_id']
detail = c.get(f'/api/quiz/sessions/{sid}').json()
qs = detail['questions']
check('题目不含答案', all('answer' not in q for q in qs))

# 3. 作答四连：第一题按正确答案、第二题空提交、其余随便
first = qs[0]
detail_reveal = c.get(f'/api/quiz/sessions/{sid}', params={'reveal': True}).json()
right_answer = next(q['answer'] for q in detail_reveal['questions'] if q['id'] == first['id'])
r1 = c.post(f'/api/quiz/sessions/{sid}/answers',
            json={'question_id': first['id'], 'answer': right_answer,
                  'confidence': 0.9, 'elapsed_ms': 4200}).json()
check('按标准答案提交判对', r1['correct'] is True, f"q={first['id']} answer={right_answer}")

r2 = c.post(f'/api/quiz/sessions/{sid}/answers',
            json={'question_id': qs[1]['id'], 'answer': None, 'confidence': 0.2,
                  'elapsed_ms': 5000}).json()
check('空提交判错且进入复习', r2['correct'] is False)

for q in qs[2:]:
    r = c.post(f'/api/quiz/sessions/{sid}/answers',
               json={'question_id': q['id'], 'answer': 'zzz-not-a-answer',
                     'elapsed_ms': 3000}).json()
    check(f'作答 {q["id"][:26]}…', r['correct'] is False)
check('会话自动收尾', r2['session_finished'] or r['session_finished'])

res = c.get(f'/api/quiz/sessions/{sid}/result').json()
check('结算正确', res['total'] == 4 and res['correct'] == 1, f"correct={res['correct']}/{res['total']}")

# 4. 复习卡片与掌握度（断言容许重复运行：历史作答只增不减）
due = c.get('/api/review/due', params={'pack_id': 'english-vocab'}).json()
ov2 = c.get('/api/packs/english-vocab/overview').json()
check('已产生复习卡片', ov2['attempted_questions'] >= 4, f"attempted={ov2['attempted_questions']} due={due['count']}")
check('作答后正确率统计', ov2['attempts'] >= 4 and ov2['accuracy'] is not None)
check('掌握度投影非空', ov2['overall_mastery'] < 0.5, f"mastery={ov2['overall_mastery']:.3f}")

# 5. AI 教师（环境配了真实模型则真调，否则 mock）
ai = c.post('/api/ai/teacher', json={'pack_id': 'english-vocab', 'mode': 'hint',
                                     'question_id': first['id'], 'message': '提示一下'})
check('AI提示接口可用', ai.status_code == 200 and bool(ai.json().get('reply')),
      f"model={ai.json().get('model')} mock={ai.json().get('mock')}")
ai2 = c.post('/api/ai/teacher', json={'pack_id': 'english-vocab', 'mode': 'explain',
                                      'question_id': first['id'], 'message': '讲解'})
check('AI讲解接口可用', ai2.status_code == 200 and bool(ai2.json().get('reply')))

# 6. 前端资源
check('SPA 首页', c.get('/').status_code == 200 and b'AnyLearn' in c.get('/').content)
check('静态JS', c.get('/static/app.js').status_code == 200)

print()
print('FAILED:', fails if fails else '无 —— 全部通过')
sys.exit(1 if fails else 0)
