/* AnyLearn 学习框架 + 项目层前端视图（零构建，挂到主 app.js 的 SPA 上）。
   设计原则：页面只呈现框架给的结构，不自己发明等级或判分。
   等级一律来自后端 concept_ability 投影，按钮文案只描述「下一步做什么」。 */

const LEVEL_NAMES = ['未接触', '识别', '解释', '应用', '诊断', '迁移'];
const STEP_LABEL = {
  diagnose: '诊断', explain: '讲解', socratic: '苏格拉底追问',
  feynman: '费曼讲解', practice: '动手', verify: '独立验收', review: '复习',
};
const VERDICT_LABEL = { pass: '通过', fail: '未通过', pending: '待评审' };
const STATUS_LABEL = {
  locked: '未解锁', available: '可开始', in_progress: '进行中',
  in_review: '待评审', completed: '已完成', ready: '待开始', passed: '已通过',
};

function levelChip(level) {
  return `<span class="al-level al-lv-${level}">L${level} ${LEVEL_NAMES[level] || ''}</span>`;
}

function progressBar(done, total) {
  const p = total ? Math.round((done / total) * 100) : 0;
  return `<div class="al-bar"><i style="width:${p}%"></i></div>`;
}

/* ---------- 学习路径 ---------- */

async function viewLearn() {
  if (!S.packId) return needPack();
  app.innerHTML = `<div class="empty">加载课程…</div>`;
  let data;
  try {
    data = await api(`/api/packs/${S.packId}/courses`);
  } catch (e) {
    app.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  const courses = data.courses || [];
  if (!courses.length) {
    app.innerHTML = intro('LEARN / 学习路径', '这个内容包还没有课程。',
      '课程由内容包的 <code>data/curriculum.json</code> 提供。学习框架本身不含学科内容。');
    return;
  }
  const html = [intro('LEARN / 学习路径', courses[0].title,
    `${esc(courses[0].goal || '')}${courses[0].audience ? ' · ' + esc(courses[0].audience) : ''}`)];
  for (const c of courses) {
    html.push(`<div class="al-course-head">${esc(c.title)} <span class="note">v${esc(c.version)}</span></div>`);
    html.push('<div class="al-units">');
    for (const u of c.units) {
      const p = u.steps_total ? u.steps_done / u.steps_total : 0;
      html.push(`<a class="al-unit ${u.done ? 'done' : ''}" href="#/unit?id=${encodeURIComponent(u.unit_id)}">
        <div class="al-unit-top">
          <span class="al-unit-title">${esc(u.title)}</span>
          ${u.done ? '<span class="al-flag done">已掌握</span>' : ''}
        </div>
        <p class="al-unit-obj">${esc(u.objective || '')}</p>
        <div class="al-unit-meta">
          ${progressBar(u.steps_done, u.steps_total)}
          <span class="note">${u.steps_done}/${u.steps_total} 步 · 约 ${u.est_minutes} 分钟</span>
        </div>
      </a>`);
    }
    html.push('</div>');
  }
  app.innerHTML = html.join('');
}

/* ---------- 单元详情 ---------- */

async function viewUnit(params) {
  const unitId = params.get('id');
  if (!unitId) { location.hash = '#/learn'; return; }
  app.innerHTML = `<div class="empty">加载单元…</div>`;
  let data;
  try {
    data = await api(`/api/units/${encodeURIComponent(unitId)}`);
  } catch (e) {
    app.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  const { unit, steps, blockers } = data;
  const html = [intro('UNIT / 单元', unit.title, esc(unit.objective || ''))];

  // 概念与等级
  html.push('<div class="al-panel"><div class="al-panel-head">概念掌握</div><div class="al-concepts">');
  for (const c of unit.concepts) {
    html.push(`<div class="al-concept">
      <div class="al-concept-name">${esc(c.name)} ${levelChip(c.level)}</div>
      <div class="al-concept-meta">
        <span class="note">目标 L${c.target} · 独立通过 ${c.independent_passes} 次${
          c.assisted_passes ? ` · 辅助 ${c.assisted_passes} 次` : ''}</span>
        <a class="al-link" href="#/diagnose?id=${encodeURIComponent(c.concept_id)}">卡在哪</a>
      </div>
    </div>`);
  }
  html.push('</div></div>');

  // 卡点
  if (blockers && blockers.length) {
    html.push('<div class="al-panel warn"><div class="al-panel-head">当前卡点</div>');
    for (const b of blockers) {
      html.push(`<div class="al-blocker"><b>${esc(b.concept)}</b>
        <ul>${b.reasons.map(r => `<li>${esc(r.detail)}</li>`).join('')}</ul>
        <p class="al-next">下一步：${esc(b.next_action)}</p></div>`);
    }
    html.push('</div>');
  }

  // 步骤
  html.push('<div class="al-panel"><div class="al-panel-head">教学步骤</div><ol class="al-steps">');
  for (const s of steps) {
    html.push(`<li class="al-step ${s.done ? 'done' : ''}">
      <div class="al-step-ord">${s.ord}</div>
      <div class="al-step-body">
        <div class="al-step-top">
          <span class="al-step-kind k-${s.kind}">${STEP_LABEL[s.kind] || s.kind}</span>
          <span class="al-step-title">${esc(s.title)}</span>
        </div>
        ${s.content_ref ? `<div class="al-ref">出处：${esc(s.content_ref)}</div>` : ''}
        ${renderStepExtra(s)}
        <div class="al-step-actions">
          ${s.done ? '<span class="al-flag done">已完成</span>'
            : `<button class="al-mini" data-step="${esc(s.id)}">标记完成</button>`}
        </div>
      </div>
    </li>`);
  }
  html.push('</ol></div>');
  app.innerHTML = html.join('');

  app.querySelectorAll('[data-step]').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api('/api/learn/steps/done', {
          method: 'POST',
          body: { pack_id: S.packId, unit_id: unit.unit_id, step_id: btn.dataset.step },
        });
        toast('已记录');
        viewUnit(params);
      } catch (e) {
        toast(e.message); btn.disabled = false;
      }
    };
  });
  bindStepTools(unit, steps);
}

function renderStepExtra(s) {
  const c = s.config || {};
  const bits = [];
  if (s.kind === 'socratic') {
    bits.push(`<div class="al-tool">
      <textarea class="al-input" data-socratic="${esc(s.concept_id || '')}" rows="3"
        placeholder="写下你的回答，教师会追问你一句"></textarea>
      <button class="al-mini" data-probe="${esc(s.concept_id || '')}">让教师追问</button>
      <div class="al-probe"></div></div>`);
  }
  if (s.kind === 'feynman') {
    bits.push(`<div class="al-tool">
      <textarea class="al-input" data-feynman="${esc(s.concept_id || '')}" rows="5"
        placeholder="用给初学者讲的口吻写一遍，越具体越好"></textarea>
      <button class="al-mini" data-feyn="${esc(s.concept_id || '')}">让教师看哪没讲清</button>
      <div class="al-feyn"></div></div>`);
  }
  if (c.task) bits.push(`<div class="al-task">任务：${esc(c.task)}</div>`);
  if (c.rubric) bits.push(`<div class="al-rubric">评分要点：${c.rubric.map(r => esc(r)).join(' · ')}</div>`);
  if (s.kind === 'verify' && c.independent) {
    bits.push('<div class="al-task">这一关要求独立完成，不要用提示。</div>');
  }
  return bits.join('');
}

function bindStepTools(unit, steps) {
  app.querySelectorAll('[data-probe]').forEach(btn => {
    btn.onclick = async () => {
      const cid = btn.dataset.probe;
      const ta = app.querySelector(`[data-socratic="${CSS.escape(cid)}"]`);
      btn.disabled = true;
      try {
        const r = await api('/api/tutor/socratic', {
          method: 'POST', body: { concept_id: cid, utterance: ta ? ta.value : '' },
        });
        app.querySelectorAll('.al-probe').forEach(el => {
          if (el.closest('.al-tool')?.contains(btn)) {
            el.innerHTML = `<div class="al-qa"><b>追问：</b>${esc(r.question)}
              ${r.targets ? `<div class="note">指向：${esc(r.targets)}</div>` : ''}
              ${r.degraded ? '<div class="note">（离线 mock，未接真实模型）</div>' : ''}</div>`;
          }
        });
      } catch (e) { toast(e.message); }
      btn.disabled = false;
    };
  });
  app.querySelectorAll('[data-feyn]').forEach(btn => {
    btn.onclick = async () => {
      const cid = btn.dataset.feyn;
      const ta = app.querySelector(`[data-feynman="${CSS.escape(cid)}"]`);
      if (!ta || ta.value.trim().length < 20) { toast('先把讲解写完整一点'); return; }
      btn.disabled = true;
      try {
        const r = await api('/api/tutor/feynman-review', {
          method: 'POST', body: { concept_id: cid, explanation: ta.value },
        });
        const box = btn.parentElement.querySelector('.al-feyn');
        const items = (r.items || []).map(i =>
          `<li class="${i.met ? 'ok' : 'gap'}">${i.met ? '✓' : '✗'} ${esc(i.item)}
             <span class="note">${esc(i.reason)}</span></li>`).join('');
        const gaps = (r.gaps || []).map(g => `<li>${esc(g)}</li>`).join('');
        box.innerHTML = `<div class="al-review">
          <div class="al-review-head">${esc(VERDICT_LABEL[r.verdict] || r.verdict)} · ${r.met}/${r.total} 条讲清
            ${r.degraded ? '<span class="note">（离线 mock，不作判定）</span>' : ''}</div>
          <ul class="al-rubric-list">${items}</ul>
          ${gaps ? `<div class="al-gaps"><b>还缺什么：</b><ul>${gaps}</ul></div>` : ''}
        </div>`;
      } catch (e) { toast(e.message); }
      btn.disabled = false;
    };
  });
}

/* ---------- 卡点诊断 ---------- */

async function viewDiagnose(params) {
  const cid = params.get('id');
  if (!cid) { location.hash = '#/learn'; return; }
  app.innerHTML = `<div class="empty">诊断中…</div>`;
  let d;
  try {
    d = await api(`/api/concepts/${encodeURIComponent(cid)}/diagnose`);
  } catch (e) {
    app.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  const html = [intro('DIAGNOSE / 卡点诊断', d.concept,
    `当前等级 ${levelChip(d.level)}，不是分数，是证据推出来的。`)];
  if (!d.blocked) {
    html.push('<div class="al-panel ok"><div class="al-panel-head">没有卡点</div>');
    html.push(`<p class="al-next">下一步：${esc(d.next_action)}</p></div>`);
  } else {
    html.push('<div class="al-panel warn"><div class="al-panel-head">为什么卡住</div><ul class="al-reasons">');
    for (const r of d.reasons) {
      html.push(`<li><b>${esc(r.code)}</b>：${esc(r.detail)}`);
      if (r.prerequisites) {
        html.push('<ul>' + r.prerequisites.map(p =>
          `<li>${esc(p.name)} 当前 L${p.level}，需要 L${r.required_level || '—'}</li>`).join('') + '</ul>');
      }
      html.push('</li>');
    }
    html.push(`</ul><p class="al-next">下一步：${esc(d.next_action)}</p></div>`);
  }
  app.innerHTML = html.join('');
}

/* ---------- 项目 ---------- */

async function viewProjects() {
  if (!S.packId) return needPack();
  app.innerHTML = `<div class="empty">加载项目…</div>`;
  let data;
  try {
    data = await api(`/api/packs/${S.packId}/projects`);
  } catch (e) {
    app.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  const list = data.projects || [];
  if (!list.length) {
    app.innerHTML = intro('PROJECT / 实战项目', '这个内容包还没有项目。',
      '项目由 <code>data/projects.json</code> 提供。项目验收是升到 L4/L5 的唯一途径。');
    return;
  }
  const html = [intro('PROJECT / 实战项目',
    '做出来的东西，才算数。',
    '做题最多到 L4；L5 必须由真实产物验收兑现。')];
  html.push('<div class="al-projects">');
  for (const p of list) {
    const total = p.milestones.length;
    const passed = p.milestones.filter(m => m.passed).length;
    html.push(`<a class="al-proj ${p.status}" href="#/project?id=${encodeURIComponent(p.project_id)}">
      <div class="al-proj-top">
        <span class="al-proj-title">${esc(p.title)}</span>
        <span class="al-flag ${p.status}">${STATUS_LABEL[p.status] || p.status}</span>
      </div>
      <p class="al-proj-brief">${esc(p.brief)}</p>
      <div class="al-unit-meta">${progressBar(passed, total)}
        <span class="note">${passed}/${total} 里程碑</span></div>
      ${p.gate && !p.gate.open ? `<div class="al-gate">需先完成：${
        p.gate.missing.map(m => esc(m.title)).join('、')}</div>` : ''}
    </a>`);
  }
  html.push('</div>');
  app.innerHTML = html.join('');
}

async function viewProject(params) {
  const pid = params.get('id');
  if (!pid) { location.hash = '#/projects'; return; }
  app.innerHTML = `<div class="empty">加载项目…</div>`;
  let p;
  try {
    p = await api(`/api/projects/${encodeURIComponent(pid)}`);
  } catch (e) {
    app.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  const html = [intro('PROJECT / 项目', p.title, esc(p.brief))];
  if (p.goal) html.push(`<div class="al-goal">做完能证明：${esc(p.goal)}</div>`);

  if (p.gate && !p.gate.open) {
    html.push(`<div class="al-panel warn"><div class="al-panel-head">尚未解锁</div><ul class="al-reasons">`);
    for (const m of p.gate.missing) {
      html.push(`<li>${esc(m.title)} 需达到 L${m.required_level || m.min_level}
        <ul>${(m.short || []).map(s => `<li>${esc(s.concept)} 当前 L${s.level}</li>`).join('')}</ul></li>`);
    }
    html.push('</ul><a class="al-link" href="#/learn">去学前置单元 →</a></div>');
    app.innerHTML = html.join('');
    return;
  }

  html.push('<div class="al-panel"><div class="al-panel-head">里程碑与交付物</div>');
  for (const m of p.milestones) {
    html.push(`<div class="al-ms ${m.passed ? 'passed' : ''}">
      <div class="al-ms-head">
        <span>${esc(m.title)}</span>
        <span class="al-flag ${m.passed ? 'passed' : 'ready'}">${m.passed ? '已通过' : '未完成'}</span>
      </div>
      <p class="al-ms-obj">${esc(m.objective || '')}</p>
      <div class="al-deliverables">`);
    for (const d of m.deliverables) {
      const v = d.last_verdict;
      html.push(`<div class="al-del">
        <div class="al-del-top">
          <span class="al-del-title">${esc(d.title)}</span>
          <span class="al-kind">${esc(d.kind)}</span>
          ${d.required ? '' : '<span class="note">选做</span>'}
          ${v ? `<span class="al-verdict v-${v}">${VERDICT_LABEL[v] || v}</span>` : ''}
        </div>
        ${d.kind === 'explain' ? `
          <textarea class="al-input" data-exp="${esc(d.deliverable_id)}" rows="4"
            placeholder="写上你的解释（结构由系统检查，语义由教师评审）"></textarea>
          <button class="al-mini" data-submit="${esc(d.deliverable_id)}" data-kind="explain">提交待评审</button>`
        : `<button class="al-mini" data-submit="${esc(d.deliverable_id)}" data-kind="${esc(d.kind)}">验收这一项</button>`}
      </div>`);
    }
    html.push('</div></div>');
  }
  html.push('</div>');

  // 待评审区
  try {
    const pend = await api(`/api/projects/${encodeURIComponent(pid)}/pending`);
    if (pend.pending && pend.pending.length) {
      html.push('<div class="al-panel"><div class="al-panel-head">待评审</div>');
      for (const s of pend.pending) {
        html.push(`<div class="al-pending">
          <div class="al-del-top"><span>${esc(s.title)}</span>
            <button class="al-mini" data-ai="${s.id}">让 AI 教师评审</button></div>
        </div>`);
      }
      html.push('</div>');
    }
  } catch (e) { /* 无 pending 接口数据时忽略 */ }

  app.innerHTML = html.join('');
  bindProjectActions(pid);
}

function bindProjectActions(pid) {
  app.querySelectorAll('[data-submit]').forEach(btn => {
    btn.onclick = async () => {
      const did = btn.dataset.submit;
      const kind = btn.dataset.kind;
      const body = { payload: {} };
      if (kind === 'explain') {
        const ta = app.querySelector(`[data-exp="${CSS.escape(did)}"]`);
        if (!ta || ta.value.trim().length < 20) { toast('解释写得太短了'); return; }
        body.payload = { explain: ta.value };
      }
      btn.disabled = true;
      try {
        const r = await api(`/api/deliverables/${encodeURIComponent(did)}/submit`, {
          method: 'POST', body,
        });
        const bad = (r.checks || []).filter(c => !c.ok).map(c => c.detail).join('；');
        toast(r.verdict === 'pass' ? '通过' :
          r.verdict === 'pending' ? '已提交，等待评审' : `未通过：${bad || '检查不通过'}`);
        viewProject(new URLSearchParams({ id: pid }));
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
  app.querySelectorAll('[data-ai]').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const r = await api('/api/submissions/ai-review', {
          method: 'POST', body: { submission_id: Number(btn.dataset.ai) },
        });
        toast(r.applied && r.applied.verdict !== 'pending'
          ? `评审结论：${VERDICT_LABEL[r.applied.verdict]}` : '评审未能给出结论，仍待人工');
        viewProject(new URLSearchParams({ id: pid }));
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
}

/* ---------- 挂载到路由 ---------- */

(function mountLearnRoutes() {
  // app.js 用函数声明定义了 route / PAGES / renderNav，同作用域下可直接改写
  PAGES.splice(PAGES.findIndex(p => p[0] === 'packs'), 0,
    ['learn', '学习路径', '#/learn'],
    ['projects', '项目', '#/projects']);
  const extra = {
    learn: viewLearn, unit: viewUnit, diagnose: viewDiagnose,
    projects: viewProjects, project: viewProject,
  };
  const origRoute = route;
  route = function () {
    const hash = location.hash || '#/dashboard';
    const page = hash.slice(2).split('?')[0];
    if (!extra[page]) return origRoute();
    renderNav(page);
    extra[page](new URLSearchParams(hash.split('?')[1] || ''), app);
    window.scrollTo(0, 0);
  };
  const origNav = renderNav;   // 保留引用，避免被上方同名改写影响
  void origNav;
  window.__anylearnLearnRoutes = { extra };
})();
