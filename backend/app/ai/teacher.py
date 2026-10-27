"""AI 教师：人设与学科话术完全由内容包提供，框架只负责组装上下文。

模式：
- hint   答前提示（系统指令强制不泄露答案/选项）
- explain 答后讲解（携带标准答案与解析）
- chat   自由追问
"""
import json
from datetime import datetime, timezone

from ..domain.quiz import LETTERS
from .gateway import ModelGateway, get_model_gateway
from .schemas import Message

DEFAULT_PERSONA = (
    '你是一位耐心的学科教师。学生正在使用一套自适应学习系统。'
    '回答用中文，简洁分层，先给结论再给依据，必要时举例。'
)

MODE_INSTRUCTIONS = {
    'hint': '当前学生还未作答。你只能给启发式提示：指出应回顾的考点方向、题干中的关键线索、'
            '排除思路。绝对禁止直接或间接泄露正确答案、正确选项字母或答案文本。',
    'explain': '学生已作答完毕。请基于标准答案与解析，给出结构化讲解：为什么正确答案对、'
               '常见错误原因、本题涉及的考点总结。',
    'chat': '学生自由提问。可以围绕题目、考点、学科知识展开，答案已对student可见，可正常讨论。',
}


def _question_block(question, reveal: bool) -> str:
    if question is None:
        return '（当前无特定题目上下文，按一般学科问题回答）'
    lines = [f'题目[{question["type"]}]：{question["stem"]}']
    options = question.get('options') or []
    if options:
        for i, opt in enumerate(options):
            lines.append(f'{LETTERS[i]}. {opt}')
    if reveal:
        lines.append(f'标准答案：{question["answer"]}')
        if question.get('explanation'):
            lines.append(f'参考解析：{question["explanation"]}')
    return '\n'.join(lines)


def build_messages(pack: dict, mode: str, question: dict | None, history: list[dict],
                   user_text: str) -> list[Message]:
    manifest = json.loads(pack['manifest_json']) if isinstance(pack.get('manifest_json'), str) else (pack or {})
    persona = (manifest.get('ai') or {}).get('teacher_persona') or DEFAULT_PERSONA
    system = (
        f'{persona}\n\n学科领域：{manifest.get("name", "未命名学习包")}\n'
        f'教学模式：{mode}。{MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["chat"])}\n\n'
        f'{_question_block(question, reveal=mode in ("explain", "chat"))}'
    )
    messages = [Message(role='system', content=system)]
    for h in (history or [])[-10:]:
        role = h.get('role') if h.get('role') in ('user', 'assistant') else 'user'
        messages.append(Message(role=role, content=str(h.get('content', ''))[:4000]))
    messages.append(Message(role='user', content=user_text or '请讲解这道题'))
    return messages


async def teacher_reply(db, pack_id: str, mode: str, user_text: str,
                        question_id: str | None = None, history: list[dict] | None = None,
                        gateway: ModelGateway | None = None) -> dict:
    pack = db.execute('SELECT * FROM packs WHERE id=?', (pack_id,)).fetchone()
    if pack is None:
        raise LookupError(f'内容包不存在: {pack_id}')
    question = None
    if question_id:
        row = db.execute('SELECT * FROM questions WHERE id=? AND pack_id=?', (question_id, pack_id)).fetchone()
        if row is None:
            raise LookupError(f'题目不存在或不属于该内容包: {question_id}')
        question = {
            'id': row['id'], 'type': row['type'], 'stem': row['stem'],
            'options': json.loads(row['options_json'] or '[]'),
            'answer': row['answer'], 'explanation': row['explanation'],
        }
    gw = gateway or get_model_gateway()
    task = {'hint': 'tutor_hint', 'explain': 'tutor_explanation'}.get(mode, 'chat')
    result = await gw.generate(task, build_messages(dict(pack), mode, question, history or [], user_text))

    now = datetime.now(timezone.utc).isoformat()
    db.execute('INSERT INTO ai_conversations (pack_id,question_id,mode,role,content,created_at) '
               'VALUES (?,?,?,?,?,?)', (pack_id, question_id, mode, 'user', user_text, now))
    db.execute('INSERT INTO ai_conversations (pack_id,question_id,mode,role,content,created_at) '
               'VALUES (?,?,?,?,?,?)', (pack_id, question_id, mode, 'assistant', result.raw_text, now))
    return {
        'reply': result.raw_text,
        'mode': mode,
        'model': result.model_name,
        'provider': result.provider_name,
        'mock': result.provider_name == 'mock',
    }


def conversation_history(db, pack_id: str, question_id: str | None = None, limit: int = 50) -> list[dict]:
    qfilter = 'AND question_id=?' if question_id else ''
    params: list = [pack_id]
    if question_id:
        params.append(question_id)
    rows = db.execute(
        f'SELECT role, content, mode, created_at FROM ai_conversations WHERE pack_id=? {qfilter} '
        f'ORDER BY id DESC LIMIT ?', (*params, limit)).fetchall()
    return [{'role': r['role'], 'content': r['content'], 'mode': r['mode'],
             'created_at': r['created_at']} for r in reversed(rows)]
