/* AnyLearn 前端（零构建 SPA）—— 与公考 Learning OS 共用同一套 UI 语言。
   学科文案/模块名/主题色全部来自内容包；结构类名沿用公考 globals.css 体系。 */
'use strict';

const LETTERS = 'ABCDEFGH';
const CONF = [
  { v: 0.2, label: '纯蒙题' },
  { v: 0.5, label: '半猜' },
  { v: 0.9, label: '有信心' },
];
const SELF_RATE = [
  { v: 'again', label: '又忘了' },
  { v: 'hard', label: '有点难' },
  { v: 'good', label: '记住了' },
  { v: 'easy', label: '很简单' },
];
const TYPE_LABEL = { single_choice: '单选', multi_choice: '多选', cloze: '填空', self_rate: '自评卡', short_answer: '简答' };

const S = {
  packs: [],
  packId: localStorage.getItem('anylearn.pack') || null,
  session: null,
  chat: [],
};

/* ---------- 基础工具 ---------- */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg, ms = 2800) {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function md(s) {
  return esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
}

function pct(x, digits = 0) { return x == null ? '—' : (x * 100).toFixed(digits) + '%'; }
function num(x) { return x == null ? '—' : Number(x).toLocaleString('zh-CN'); }

function masteryBadge(m, attempted) {
  if (!attempted || m == null) return '<span class="m-badge na">未测</span>';
  const cls = m < 0.4 ? 'lo' : m < 0.7 ? 'mid' : 'hi';
  return `<span class="m-badge ${cls}">${(m * 100).toFixed(0)}</span>`;
}

function currentPack() { return S.packs.find(p => p.id === S.packId); }

function applyTheme(pack) {
  // 内容包可覆盖主色；未指定时保持与公考一致的墨绿
  const color = pack?.theme?.primary_color || '#296044';
  document.documentElement.style.setProperty('--accent', color);
}

function intro(eyebrow, title, desc) {
  return `<div class="intro"><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1><p>${desc}</p></div>`;
}

function needPack() {
  app.innerHTML = intro('GET STARTED / 开始使用', '先注入一个内容包。',
    '框架本身不含任何学科内容，去 <a href="#/packs">内容包</a> 安装或导入后即可开始。');
}

/* ---------- 路由 ---------- */

const PAGES = [
  ['dashboard', '学习概览', '#/dashboard'],
  ['tree', '知识框架', '#/tree'],
  ['quiz', '训练', '#/quiz'],
  ['review', '到期复习', '#/review'],
  ['teacher', '问老师', '#/teacher'],
  ['packs', '内容包', '#/packs'],
];

function route() {
  const hash = location.hash || '#/dashboard';
  const [page, query] = hash.slice(2).split('?');
  const params = new URLSearchParams(query || '');
  renderNav(page);
  const views = {
    dashboard: viewDashboard, quiz: viewQuiz, review: viewReview,
    tree: viewTree, teacher: viewTeacher, packs: viewPacks,
  };
  (views[page] || viewDashboard)(params, app);
  window.scrollTo(0, 0);
}

function renderNav(active) {
  document.getElementById('nav').innerHTML = PAGES.map(
    ([id, label, href]) => `<a href="${href}" class="${id === active ? 'active' : ''}">${label}</a>`
  ).join('');
}

async function refreshPacks() {
  const data = await api('/api/packs');
  S.packs = data.packs;
  S.availableRoot = data.available_in_root;
  if (!S.packId && S.packs.length) S.packId = S.packs[0].id;
  applyTheme(currentPack());
  const sel = document.getElementById('packSelect');
  sel.innerHTML = S.packs.map(p =>
    `<option value="${esc(p.id)}" ${p.id === S.packId ? 'selected' : ''}>${esc(p.name)}</option>`).join('') ||
    '<option>（暂无内容包）</option>';
  sel.onchange = () => {
    S.packId = sel.value;
    S.session = null;
    localStorage.setItem('anylearn.pack', S.packId);
    applyTheme(currentPack());
    route();
  };
}

const app = document.getElementById('app');

/* ---------- 学习概览 ---------- */

async function viewDashboard() {
  if (!S.packId) return needPack();
  const ov = await api(`/api/packs/${S.packId}/overview`);
  const pack = currentPack();
  const unseen = ov.questions - ov.attempted_questions;
  const focusTitle = ov.due_reviews > 0
    ? `先清掉 ${ov.due_reviews} 道到期复习`
    : unseen > 0 ? '继续推进未做过的题' : '把所有题再刷一轮';
  const focusDesc = ov.due_reviews > 0
    ? '间隔重复算法认为这些题正处在遗忘边缘，此刻重刷的收益最高。'
    : unseen > 0
      ? `还有 ${num(unseen)} 道题从未作答。系统会优先推送新题，避免在同一批题上空转。`
      : '全部题目都已作答，进入复习模式按遗忘曲线巩固。';

  app.innerHTML = `
    ${intro('DASHBOARD / 学习概览', '用真实作答，看见下一步。',
      `当前内容包：<b>${esc(ov.pack_name)}</b>。所有指标都由本机保存的作答记录计算，可随时重新生成。`)}
    <section class="metric-grid" aria-label="学习指标">
      <article class="featured"><small>整体掌握度</small><strong>${pct(ov.overall_mastery)}</strong><span>按知识节点权重加权</span></article>
      <article><small>题目总数</small><strong>${num(ov.questions)}</strong><span>${ov.modules.length} 个模块</span></article>
      <article><small>已作答题目</small><strong>${num(ov.attempted_questions)}</strong><span>未作答 ${num(unseen)} 道</span></article>
      <article><small>正确率</small><strong>${pct(ov.accuracy, 1)}</strong><span>最近 ${num(ov.attempts)} 次作答</span></article>
      <article><small>待复习</small><strong>${num(ov.due_reviews)}</strong><span>FSRS 到期卡片</span></article>
      <article><small>活跃天数</small><strong>${num(ov.active_days)}</strong><span>有正式作答的日期</span></article>
    </section>

    <div class="decision-grid">
      <div class="focus-card">
        <span class="eyebrow">NEXT / 下一步</span>
        <h2>${esc(focusTitle)}</h2>
        <p>${esc(focusDesc)}</p>
        <a class="primary-link" href="${ov.due_reviews > 0 ? '#/review' : '#/quiz'}">
          ${ov.due_reviews > 0 ? '开始到期复习' : '开始训练'}
        </a>
      </div>
      <div class="dashboard-section">
        <span class="eyebrow">EVIDENCE / 学习证据</span>
        <h2>这些数字从哪来</h2>
        <p style="font-size:13px;color:var(--muted);margin:0">只有正式作答计入统计；教学复盘与提示重答不污染掌握度。</p>
        <dl class="metrics" style="margin-top:14px;border-bottom:none">
          <div><small>正式作答</small><strong>${num(ov.attempts)}</strong></div>
          <div><small>作答正确率</small><strong>${pct(ov.accuracy, 1)}</strong></div>
          <div><small>复习到期</small><strong>${num(ov.due_reviews)}</strong></div>
        </dl>
      </div>
    </div>

    <section class="dashboard-section">
      <div class="section-heading">
        <h2>知识框架</h2>
        <span>共 ${ov.modules.length} 个模块 · 点模块直接开练</span>
      </div>
      <div class="knowledge-groups">
        ${ov.modules.map(m => `
          <article data-module="${esc(m.id)}" title="点此训练 ${esc(m.name)}">
            <h3>${esc(m.name)}</h3>
            <div class="knowledge-row">
              <div><strong>${num(m.questions)} 题</strong><span>已练 ${num(m.attempted)}${m.due ? ` · 待复习 ${m.due}` : ''}</span></div>
              <div class="mastery-bar"><i style="width:${m.attempted ? (m.mastery ?? 0) * 100 : 0}%"></i></div>
              <b>${m.attempted ? pct(m.mastery) : '—'}</b>
            </div>
            <div class="knowledge-row" style="margin-top:6px">
              <div><strong style="font-size:11px;font-weight:600;color:var(--muted)">正确率</strong></div>
              <div class="mastery-bar"><i style="width:${(m.accuracy ?? 0) * 100}%"></i></div>
              <b>${pct(m.accuracy)}</b>
            </div>
          </article>`).join('')}
      </div>
    </section>
    <footer><span>ANYLEARN · 注入式学习框架</span><span>${esc(pack?.name || '')} · v${esc(pack?.version || '')}</span></footer>`;

  app.querySelectorAll('.knowledge-groups article[data-module]').forEach(el =>
    el.onclick = () => { location.hash = `#/quiz?module=${encodeURIComponent(el.dataset.module)}`; });
}

/* ---------- 训练：配置 ---------- */

async function viewQuiz(params) {
  if (!S.packId) return needPack();
  if (S.session) return renderQuestion();
  const ov = await api(`/api/packs/${S.packId}/overview`);
  const preselect = params.get('module');
  const mode = params.get('mode') === 'review' ? 'review' : 'practice';
  app.innerHTML = `
    ${intro(mode === 'review' ? 'REVIEW DRILL / 到期复习重刷' : 'PRACTICE / 训练',
      mode === 'review' ? '在该复习的时候，重新独立做一次。' : '每一次作答，都是进步的起点。',
      mode === 'review'
        ? '纯净题目重做，不提前泄露答案。作答后再评测，检验真实记忆。'
        : '先独立思考，再记录判断。让学习留下真实的证据。')}
    <div class="workspace single">
      <section class="card">
        <div class="card-top"><span>${mode === 'review' ? '🔄 到期重刷' : '开始一组训练'}</span><span>${esc(ov.pack_name)}</span></div>
        <div style="margin-top:22px">
          <div class="eyebrow" style="letter-spacing:1px">MODULE / 模块</div>
          <div class="chip-row" id="modRow">
            ${ov.modules.map(m => `<span class="chip ${m.id === preselect ? 'sel' : ''}" data-id="${esc(m.id)}">${esc(m.name)}<span style="color:var(--muted);font-size:11px;margin-left:6px">${num(m.questions)}</span></span>`).join('')}
          </div>
        </div>
        <div style="margin-top:24px">
          <div class="eyebrow" style="letter-spacing:1px">COUNT / 题量</div>
          <div class="chip-row" id="cntRow">
            ${[5, 10, 20, 30].map(n => `<span class="chip ${n === 10 ? 'sel' : ''}" data-n="${n}">${n} 题</span>`).join('')}
          </div>
        </div>
        <div class="submit-row">
          <span class="muted">不选模块 = 全部模块；系统优先推送未做过的题</span>
          <button class="primary" id="startBtn">开始训练</button>
        </div>
      </section>
    </div>`;

  app.querySelectorAll('#modRow .chip').forEach(c => c.onclick = () => c.classList.toggle('sel'));
  app.querySelectorAll('#cntRow .chip').forEach(c => c.onclick = () => {
    app.querySelectorAll('#cntRow .chip').forEach(x => x.classList.remove('sel'));
    c.classList.add('sel');
  });
  app.querySelector('#startBtn').onclick = async () => {
    const module_ids = [...app.querySelectorAll('#modRow .chip.sel')].map(c => c.dataset.id);
    const count = +app.querySelector('#cntRow .chip.sel').dataset.n;
    const btn = app.querySelector('#startBtn');
    btn.disabled = true;
    try {
      const s = await api('/api/quiz/sessions', {
        method: 'POST', body: { pack_id: S.packId, module_ids, count, mode },
      });
      S.session = {
        id: s.session_id, detail: await api(`/api/quiz/sessions/${s.session_id}`),
        idx: 0, subs: {}, sel: {}, multi: {}, text: {}, conf: {}, hints: {}, qStart: Date.now(),
      };
      renderQuestion();
    } catch (e) {
      btn.disabled = false;
      toast('创建会话失败：' + e.message, 4200);
    }
  };
}

/* ---------- 训练：答题 ---------- */

function renderQuestion() {
  const st = S.session;
  const qs = st.detail.questions;
  if (st.idx >= qs.length) return renderSummary();
  const q = qs[st.idx];
  const sub = st.subs[q.id];
  const hint = st.hints[q.id];
  const answeredCount = Object.keys(st.subs).length;

  let bodyHtml = '';
  if (q.type === 'single_choice' || q.type === 'multi_choice') {
    const multi = q.type === 'multi_choice';
    const picked = multi ? (st.multi?.[q.id] || []) : null;
    bodyHtml = (multi ? '<div class="eyebrow" style="letter-spacing:1px;margin-bottom:8px">多选题 · 选出所有正确项</div>' : '') +
      `<fieldset class="options">${q.options.map((o, i) => {
      const letter = LETTERS[i];
      let cls = 'option';
      if (sub) {
        const inAnswer = sub.answer.includes(letter);
        const chosen = multi ? (sub.gave || '').includes(letter) : letter === sub.gave;
        if (inAnswer) cls += ' correct';
        else if (chosen) cls += ' wrong';
      } else if (multi ? picked.includes(letter) : st.sel[q.id] === i) {
        cls += ' selected';
      }
      const mark = sub
        ? (sub.answer.includes(letter) ? '<span class="mark">正确</span>'
          : ((multi ? (sub.gave || '').includes(letter) : letter === sub.gave) ? '<span class="mark">你的选择</span>' : ''))
        : '';
      return `<label class="${cls}" data-i="${i}"><span class="letter">${multi ? '☐' : '○'} ${letter}</span><span>${md(o)}</span>${mark}</label>`;
    }).join('')}</fieldset>`;
  } else if (q.type === 'cloze' || q.type === 'short_answer') {
    bodyHtml = `<input class="cloze-input" id="clozeInput" placeholder="输入你的答案…" value="${esc(st.text[q.id] || '')}" ${sub ? 'disabled' : ''}>`;
  } else if (q.type === 'self_rate') {
    bodyHtml = `<div class="selfrate-row">${SELF_RATE.map(r =>
      `<button class="${st.sel[q.id] === r.v ? 'sel' : ''}" data-v="${r.v}" ${sub ? 'disabled' : ''}>${r.label}</button>`).join('')}</div>`;
  }

  const chips = qs.map((x, i) => {
    const s = st.subs[x.id];
    const cls = s ? (s.correct ? 'correct' : 'incorrect') : (i === st.idx ? 'current' : '');
    return `<button class="quiz-chip ${cls}" data-jump="${i}" title="第 ${i + 1} 题">${i + 1}</button>`;
  }).join('');

  app.innerHTML = `
    <div class="intro" style="padding:34px 0 18px">
      <span class="eyebrow">${st.detail.mode === 'review' ? 'REVIEW / 到期重刷' : 'PRACTICE / 训练'} · ${esc(currentPack()?.name || '')}</span>
      <h1 style="font-size:24px;margin:10px 0 6px">第 ${st.idx + 1} 题 / 共 ${qs.length} 题</h1>
      <p>已作答 ${answeredCount} 题 · 未作答 ${qs.length - answeredCount} 题</p>
    </div>
    <div class="quiz-chips-bar" aria-label="答题卡">${chips}</div>
    <div class="workspace">
      <section class="card" aria-label="当前题目">
        <div class="card-top">
          <span>${TYPE_LABEL[q.type] || q.type}${(q.tags || []).length ? ' · ' + esc((q.tags || []).slice(0, 2).join(' / ')) : ''}</span>
          <span>难度 ${q.difficulty}/5 · 建议 ${q.estimated_seconds} 秒</span>
        </div>
        <div class="question-meta">
          <span class="pill">第 ${st.idx + 1} 题</span>
          ${sub ? `<span class="pill ${sub.correct ? '' : 'amber'}">${sub.correct ? '已答对' : '已答错'}</span>` : '<span class="pill grey">待作答</span>'}
        </div>
        <p class="stem">${md(q.stem)}</p>
        ${hint ? `<div class="hint-box">💡 ${md(hint.text)}</div>` : ''}
        ${bodyHtml}

        ${!sub ? `
          <fieldset class="confidence">
            <div class="legend">作答信心<span>选填 · 影响复习间隔，不影响对错</span></div>
            <div>${CONF.map(c => `<label class="${st.conf[q.id] === c.v ? 'sel' : ''}" data-c="${c.v}">${c.label}</label>`).join('')}</div>
          </fieldset>
          <div class="submit-row">
            <span class="muted">${(hint?.level || 0) < 3 ? '不确定可以求一次提示' : '提示已用尽'}</span>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              ${(hint?.level || 0) < 3 ? '<button id="hintBtn">求提示</button>' : ''}
              <button id="skipBtn">跳过看解析</button>
              <button class="primary" id="submitBtn">提交作答</button>
            </div>
          </div>` : `
          <div class="verdict ${sub.correct ? 'ok' : 'bad'}" role="status">
            ${sub.correct ? '✓ 答对了' : `✗ ${sub.wasEmpty ? '本题未作答' : '答错了'}　正确答案：${esc(sub.answer)}`}
          </div>
          <div class="explanation">
            <h4>解析 / EXPLANATION</h4>
            ${md(sub.explanation || '（本题暂无解析）')}
          </div>
          <div class="eyebrow" style="margin-top:26px;letter-spacing:1px">TEACHER / 追问</div>
          <div class="chat-box" id="qChat" style="margin-top:12px"></div>
          <div class="chat-input">
            <textarea id="qChatInput" placeholder="问老师：为什么？这个考点还有别的例子吗…" rows="1"></textarea>
            <button class="primary" id="qChatSend">问老师</button>
          </div>
          <div class="submit-row">
            <span class="muted">答错也先自己想一遍，再让老师讲</span>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button id="explainBtn">让老师讲解本题</button>
              <button class="primary" id="nextBtn">${st.idx + 1 === qs.length ? '查看结算' : '下一题'}</button>
            </div>
          </div>`}
      </section>
      <aside>
        <div class="note">
          <span class="eyebrow">HOW IT WORKS / 怎么运作</span>
          <h2>作答是最原始的证据。</h2>
          <p><b>01</b>每次作答都会被完整记录，不会被后续操作改写。</p>
          <p><b>02</b>复习间隔与掌握度都由这些记录重新计算，可随时重放。</p>
          <p><b>03</b>用了提示、超时、信心低，都会折算成更谨慎的评价。</p>
          <hr>
          <p>当前内容包：${esc(currentPack()?.name || '')}</p>
        </div>
        <p class="aside-note">提示不会直接给出答案；解析在提交后才展示。</p>
      </aside>
    </div>`;

  bindQuestion(q, sub);
}

function bindQuestion(q, sub) {
  const st = S.session;

  app.querySelectorAll('.quiz-chip[data-jump]').forEach(c => c.onclick = () => {
    st.idx = +c.dataset.jump;
    st.qStart = Date.now();
    renderQuestion();
  });

  if (sub) {
    app.querySelector('#nextBtn').onclick = () => {
      st.idx += 1;
      st.qStart = Date.now();
      renderQuestion();
    };
    app.querySelector('#explainBtn').onclick = () => sendTeacher(q, 'explain', '请完整讲解这道题');
    app.querySelector('#qChatSend').onclick = () => {
      const text = app.querySelector('#qChatInput').value.trim();
      if (text) sendTeacher(q, 'chat', text);
    };
    return;
  }

  if (q.type === 'single_choice' || q.type === 'multi_choice') {
    app.querySelectorAll('.option').forEach(el => el.onclick = () => {
      const i = +el.dataset.i;
      if (q.type === 'multi_choice') {
        st.multi = st.multi || {};
        const picked = new Set(st.multi[q.id] || []);
        const letter = LETTERS[i];
        picked.has(letter) ? picked.delete(letter) : picked.add(letter);
        st.multi[q.id] = [...picked].sort();
      } else {
        st.sel[q.id] = i;
      }
      renderQuestion();
    });
  } else if (q.type === 'self_rate') {
    app.querySelectorAll('.selfrate-row button').forEach(el => el.onclick = () => {
      st.sel[q.id] = el.dataset.v;
      renderQuestion();
    });
  } else {
    const input = app.querySelector('#clozeInput');
    if (input) {
      input.oninput = () => { st.text[q.id] = input.value; };
      input.onkeydown = e => { if (e.key === 'Enter') doSubmit(q); };
      input.focus();
    }
  }

  app.querySelectorAll('.confidence label[data-c]').forEach(c => c.onclick = () => {
    const v = +c.dataset.c;
    st.conf[q.id] = st.conf[q.id] === v ? undefined : v;
    renderQuestion();
  });

  const hintBtn = app.querySelector('#hintBtn');
  if (hintBtn) hintBtn.onclick = async () => {
    hintBtn.disabled = true;
    try {
      const r = await api('/api/ai/teacher', {
        method: 'POST',
        body: { pack_id: S.packId, mode: 'hint', question_id: q.id, message: '给一点提示' },
      });
      const level = Math.min(3, (st.hints[q.id]?.level || 0) + 1);
      st.hints[q.id] = { text: r.reply, level };
    } catch (e) { toast('提示获取失败：' + e.message, 4200); }
    renderQuestion();
  };

  app.querySelector('#submitBtn').onclick = () => doSubmit(q);
  app.querySelector('#skipBtn').onclick = () => doSubmit(q, true);
}

async function doSubmit(q, skip = false) {
  const st = S.session;
  let answer = null;
  if (!skip) {
    if (q.type === 'single_choice') {
      if (st.sel[q.id] == null) return toast('先选择一个选项，或点「跳过看解析」');
      answer = LETTERS[st.sel[q.id]];
    } else if (q.type === 'multi_choice') {
      const picked = st.multi?.[q.id] || [];
      if (!picked.length) return toast('至少选择一个选项，或点「跳过看解析」');
      answer = picked.join('');
    } else if (q.type === 'self_rate') {
      if (!st.sel[q.id]) return toast('先自评，或点「跳过看解析」');
      answer = st.sel[q.id];
    } else {
      answer = (st.text[q.id] || '').trim() || null;
    }
  }
  const wasEmpty = !answer;
  try {
    const r = await api(`/api/quiz/sessions/${st.id}/answers`, {
      method: 'POST',
      body: {
        question_id: q.id, answer,
        confidence: st.conf[q.id] ?? null,
        hint_level: st.hints[q.id]?.level || 0,
        elapsed_ms: Math.min(30 * 60 * 1000, Date.now() - (st.qStart || Date.now())),
      },
    });
    st.subs[q.id] = {
      correct: r.correct, answer: r.answer, explanation: r.explanation, wasEmpty,
      gave: (q.type === 'single_choice' || q.type === 'multi_choice')
        ? (q.type === 'multi_choice' ? (st.multi?.[q.id] || []).join('') : (st.sel[q.id] != null ? LETTERS[st.sel[q.id]] : ''))
        : (answer || null),
    };
    renderQuestion();
  } catch (e) { toast('提交失败：' + e.message, 4200); }
}

async function renderSummary() {
  const st = S.session;
  const r = await api(`/api/quiz/sessions/${st.id}/result`);
  const pack = currentPack();
  const modName = id => (pack?.modules || []).find(m => m.id === id)?.name || id;
  app.innerHTML = `
    <div class="intro"><span class="eyebrow">SUMMARY / 本组结算</span><h1>做完这一组，留下一条证据。</h1>
      <p>${st.detail.mode === 'review' ? '到期复习' : '训练'} · 共 ${r.total} 题</p></div>
    <div class="workspace single">
      <section class="card">
        <div class="card-top"><span>本组结果</span><span>正确率 ${pct(r.accuracy, 1)}</span></div>
        <div class="summary-hero">
          <div class="eyebrow">CORRECT / TOTAL</div>
          <div class="big">${r.correct} <span style="font-size:22px;color:var(--muted);font-weight:600">/ ${r.total}</span></div>
          <div class="chip-row" style="justify-content:center">
            ${Object.entries(r.by_module).map(([mid, m]) =>
              `<span class="chip static">${esc(modName(mid))} ${m.correct}/${m.total}</span>`).join('')}
          </div>
        </div>
        <div class="submit-row" style="justify-content:center">
          <span class="muted">复习卡片与掌握度已按本组作答重新计算</span>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <a class="secondary-link" href="#/dashboard">回学习概览</a>
            <a class="secondary-link" href="#/review">去到期复习</a>
            <a class="primary-link" href="#/quiz">再来一组</a>
          </div>
        </div>
      </section>
    </div>`;
  S.session = null;
}

/* ---------- 到期复习 ---------- */

async function viewReview() {
  if (!S.packId) return needPack();
  const due = await api(`/api/review/due?pack_id=${encodeURIComponent(S.packId)}&limit=200`);
  const ov = await api(`/api/packs/${S.packId}/overview`);
  app.innerHTML = `
    ${intro('REVIEW DRILL / 到期复习重刷', '在该复习的时候，重新独立做一次。',
      '纯净题目重做，不提前泄露答案。作答后再评测，检验真实记忆与解题能力。')}
    <div class="workspace">
      <section class="card" aria-label="到期复习">
        <div class="card-top"><span>🔄 到期重刷</span><span>待复习题池 ${num(due.count)} 道</span></div>
        ${due.count === 0 ? `
          <div class="empty">
            当前没有到期卡片。<br>
            先去 <a href="#/quiz">训练</a> 产生作答记录，系统会按遗忘曲线自动安排复习。
          </div>` : `
          <div class="metrics" style="margin-top:24px">
            <div><small>到期卡片</small><strong style="color:var(--accent)">${num(due.count)}</strong></div>
            <div><small>累计作答</small><strong>${num(ov.attempts)}</strong></div>
            <div><small>整体掌握度</small><strong>${pct(ov.overall_mastery)}</strong></div>
          </div>
          <div class="submit-row">
            <span class="muted">复习模式只取到期卡片，答完按新的记忆状态重排</span>
            <a class="primary-link" href="#/quiz?mode=review">开始到期复习</a>
          </div>`}
      </section>
      <aside>
        <div class="note">
          <span class="eyebrow">FSRS / 间隔重复</span>
          <h2>在该忘记之前，再想起一次。</h2>
          <p><b>01</b>答对、答错、用时、信心共同决定下次到期时间。</p>
          <p><b>02</b>用了提示或超时作对，会被判为「勉强记得」。</p>
          <p><b>03</b>到期不复习，记忆强度会持续衰减。</p>
        </div>
        <p class="aside-note">复习模式不重复记录正式作答以外的数据。</p>
      </aside>
    </div>`;
}

/* ---------- 知识框架 ---------- */

async function viewTree() {
  if (!S.packId) return needPack();
  const tree = await api(`/api/packs/${S.packId}/tree`);
  const renderNode = n => `
    <div class="tree-node">
      <div class="tree-item">
        <span class="caret" data-toggle="${esc(n.id)}">${n.children?.length ? '▾' : '·'}</span>
        <span class="name">${esc(n.name)}</span>
        <span class="qcount">${n.questions} 题</span>
        ${masteryBadge(n.mastery, n.evidence)}
      </div>
      ${n.children?.length ? `<div class="tree-children" data-children="${esc(n.id)}">${n.children.map(renderNode).join('')}</div>` : ''}
    </div>`;
  app.innerHTML = `
    ${intro('KNOWLEDGE FRAMEWORK / 知识框架', '知识地图：看得清，找得到，点得动。',
      `${esc(currentPack()?.name || '')} · 徽章颜色代表掌握度（红 &lt;40 / 黄 &lt;70 / 绿 ≥70）`)}
    <div class="workspace single">
      <section class="card">
        <div class="card-top"><span>知识树</span><span>${tree.modules.length} 个模块</span></div>
        <div style="margin-top:20px">${tree.roots.map(renderNode).join('') || '<div class="empty">该内容包未提供知识树，掌握度按模块统计。</div>'}</div>
      </section>
    </div>`;
  app.querySelectorAll('.caret[data-toggle]').forEach(c => c.onclick = () => {
    const box = app.querySelector(`[data-children="${c.dataset.toggle}"]`);
    if (!box) return;
    const hidden = box.style.display === 'none';
    box.style.display = hidden ? '' : 'none';
    c.textContent = hidden ? '▾' : '▸';
  });
}

/* ---------- 问老师 ---------- */

async function viewTeacher() {
  if (!S.packId) return needPack();
  const pack = currentPack();
  const hasPersona = !!pack?.ai?.teacher_persona;
  app.innerHTML = `
    ${intro('TEACHER / 问老师', '问得清，才学得会。',
      `${esc(pack?.name || '')} · 教师人设${hasPersona ? '由内容包注入' : '使用默认人设'}，回答会带上当前内容包上下文`)}
    <div class="workspace">
      <section class="card">
        <div class="card-top"><span>与老师对话</span><span>${S.chat.length ? S.chat.length + ' 条消息' : '新对话'}</span></div>
        <div class="chat-box" id="chat" style="margin-top:22px">
          ${S.chat.map(m => `<div class="msg ${m.role}">${md(m.content)}</div>`).join('') ||
            '<div class="empty" style="padding:20px 0">有任何问题都可以问，例如：「帮我规划本周的学习重点」</div>'}
        </div>
        <div class="chat-input">
          <textarea id="chatInput" rows="2" placeholder="输入你的问题…（Enter 发送，Shift+Enter 换行）"></textarea>
          <button class="primary" id="chatSend">发送</button>
        </div>
        <span class="mock-tip" id="mockTip" style="display:none">当前为离线 mock 模型演示；配置真实模型见 model_config.toml</span>
      </section>
      <aside>
        <div class="note">
          <span class="eyebrow">CONTEXT / 上下文</span>
          <h2>老师知道你在学什么。</h2>
          <p><b>学科</b>${esc(pack?.name || '')}</p>
          <p><b>人设</b>${hasPersona ? '内容包自定义' : '默认学科教师'}</p>
          <hr>
          <p>做题页的「求提示」只给思路，不会泄露答案。</p>
        </div>
      </aside>
    </div>`;
  const input = app.querySelector('#chatInput');
  const send = async () => {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    S.chat.push({ role: 'user', content: text });
    viewTeacher();
    try {
      const r = await api('/api/ai/teacher', {
        method: 'POST',
        body: { pack_id: S.packId, mode: 'chat', message: text, history: S.chat.slice(0, -1) },
      });
      S.chat.push({ role: 'assistant', content: r.reply });
      await viewTeacher();
      if (r.mock) document.getElementById('mockTip')?.style.setProperty('display', '');
    } catch (e) {
      S.chat.push({ role: 'assistant', content: '⚠️ ' + e.message });
      viewTeacher();
    }
  };
  app.querySelector('#chatSend').onclick = send;
  input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
}

async function sendTeacher(q, mode, text) {
  const box = document.getElementById('qChat');
  if (box) box.insertAdjacentHTML('beforeend', `<div class="msg user">${md(text)}</div>`);
  try {
    const r = await api('/api/ai/teacher', {
      method: 'POST', body: { pack_id: S.packId, mode, question_id: q.id, message: text },
    });
    if (box) box.insertAdjacentHTML('beforeend', `<div class="msg assistant">${md(r.reply)}</div>`);
  } catch (e) { toast('老师回复失败：' + e.message, 4200); }
}

/* ---------- 内容包 ---------- */

async function viewPacks() {
  await refreshPacks();
  const rows = S.packs.map(p => `
    <tr>
      <td><b>${esc(p.name)}</b><br><small>${esc(p.id)} · v${esc(p.version)}</small></td>
      <td>${num(p.questions)} 题<br><small>${num(p.nodes)} 节点 / ${p.modules.length} 模块</small></td>
      <td><small>${esc(p.source?.kind || '手工')}<br>${esc((p.updated_at || '').slice(0, 10))}</small></td>
      <td style="white-space:nowrap">
        <button class="sm ${p.id === S.packId ? 'primary' : ''}" data-use="${esc(p.id)}">${p.id === S.packId ? '使用中' : '使用'}</button>
        <button class="sm" data-reinstall="${esc(p.id)}">重装</button>
      </td>
    </tr>`).join('');
  const installable = (S.availableRoot || []).filter(a => !a.installed).map(a =>
    `<span class="chip" data-install="${esc(a.pack_id)}">${esc(a.pack_id)} · 安装</span>`).join('') ||
    '<span style="color:var(--muted);font-size:12.5px">content-packs/ 下没有待安装的新内容包</span>';

  app.innerHTML = `
    ${intro('CONTENT PACKS / 内容包', '注入什么内容包，就变成什么学习系统。',
      '内容包是本框架唯一的领域开关：放进 content-packs/ 目录即自动安装，界面、知识树、教师人设随之改变。')}
    <div class="workspace single">
      <section class="card">
        <div class="card-top"><span>已安装内容包</span><span>共 ${S.packs.length} 个</span></div>
        <table class="packs" style="margin-top:8px">
          <thead><tr><th>内容包</th><th>规模</th><th>来源 / 更新</th><th>操作</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="4"><div class="empty">尚未安装任何内容包</div></td></tr>'}</tbody>
        </table>
      </section>

      <section class="card">
        <div class="card-top"><span>从 content-packs/ 目录安装</span><span>启动时也会自动扫描</span></div>
        <div class="chip-row">${installable}</div>
        <div class="submit-row">
          <span class="muted">升级版本号后重装会更新内容，已作答的历史不受影响</span>
          <button class="primary" id="scanBtn">扫描并安装全部</button>
        </div>
      </section>

      <section class="card">
        <div class="card-top"><span>从开源社区资料导入</span><span>Anki 牌组 / JSONL 题库</span></div>
        <p style="font-size:13px;color:var(--muted);margin:14px 0 18px">
          Anki 共享牌组（.apkg）或任意 JSONL 题库，导入后自动转为标准内容包并安装。
        </p>
        <div class="form-grid">
          <div class="full"><label>Anki .apkg 文件路径（AnkiWeb shared decks 下载）</label>
            <input id="apkgPath" placeholder="例如 decks/Japanese Core 2000.apkg（绝对或相对路径）"></div>
          <div><label>包 id（可选，留空自动生成）</label><input id="apkgId" placeholder="jp-core2000"></div>
          <div><label>包名（可选）</label><input id="apkgName" placeholder="日语核心2000"></div>
          <div class="full"><button class="primary sm" id="apkgBtn">导入 Anki 牌组</button></div>

          <div class="full" style="border-top:1px solid var(--line);margin-top:8px;padding-top:16px">
            <label>JSONL 题库路径（每行一题：id/module/type/stem/options/answer/explanation）</label>
            <input id="jsonlPath" placeholder="例如 banks/my-bank.jsonl（绝对或相对路径）"></div>
          <div><label>包 id</label><input id="jsonlId" placeholder="my-bank"></div>
          <div><label>包名</label><input id="jsonlName" placeholder="我的题库"></div>
          <div class="full"><button class="primary sm" id="jsonlBtn">导入 JSONL</button></div>
        </div>
      </section>
    </div>`;

  app.querySelectorAll('[data-use]').forEach(b => b.onclick = () => {
    S.packId = b.dataset.use;
    S.session = null;
    localStorage.setItem('anylearn.pack', S.packId);
    route();
  });
  app.querySelectorAll('[data-reinstall]').forEach(b => b.onclick = () => doInstall({ pack_id: b.dataset.reinstall }));
  app.querySelectorAll('[data-install]').forEach(c => c.onclick = () => doInstall({ pack_id: c.dataset.install }));
  app.querySelector('#scanBtn').onclick = () => doInstall({});
  app.querySelector('#apkgBtn').onclick = async () => {
    const path = app.querySelector('#apkgPath').value.trim();
    if (!path) return toast('请填入 .apkg 路径');
    try {
      const r = await api('/api/import/anki', {
        method: 'POST',
        body: {
          path,
          pack_id: app.querySelector('#apkgId').value.trim() || null,
          pack_name: app.querySelector('#apkgName').value.trim() || null,
        },
      });
      toast(`导入成功：${r.pack_id}（${r.questions} 题）`);
      S.packId = r.pack_id;
      localStorage.setItem('anylearn.pack', r.pack_id);
      location.hash = '#/dashboard';
      route();
    } catch (e) { toast('导入失败：' + e.message, 5000); }
  };
  app.querySelector('#jsonlBtn').onclick = async () => {
    const path = app.querySelector('#jsonlPath').value.trim();
    const pid = app.querySelector('#jsonlId').value.trim();
    const pname = app.querySelector('#jsonlName').value.trim() || pid;
    if (!path || !pid) return toast('请填入 JSONL 路径与包 id');
    try {
      const r = await api('/api/import/jsonl', { method: 'POST', body: { path, pack_id: pid, pack_name: pname } });
      toast(`导入成功：${r.pack_id}（${r.questions} 题）`);
      S.packId = r.pack_id;
      localStorage.setItem('anylearn.pack', r.pack_id);
      location.hash = '#/dashboard';
      route();
    } catch (e) { toast('导入失败：' + e.message, 5000); }
  };
}

async function doInstall(body) {
  try {
    const r = await api('/api/packs/install', { method: 'POST', body });
    const done = (r.results || []).filter(x => x.status !== 'unchanged');
    toast(done.length
      ? done.map(x => `${x.pack_id} ${x.status}（${x.questions} 题）`).join('；')
      : '没有需要更新的内容包');
    await refreshPacks();
    viewPacks();
  } catch (e) { toast('安装失败：' + e.message, 5000); }
}

/* ---------- 启动 ---------- */

window.addEventListener('hashchange', route);
(async function init() {
  try { await refreshPacks(); } catch (e) { toast('加载内容包失败：' + e.message); }
  route();
})();
