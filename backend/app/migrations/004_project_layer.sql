-- 项目层（Project Layer）v1 —— 项目制学习的结构与证据
--
-- 与学习框架（003）的分工：
--   lesson 层回答「这个知识点你会不会」；
--   project 层回答「你能不能独立做出一个真东西」。
--
-- 单元是项目的**先修门禁**，不是项目本身。验收对象是可交付的产物（代码/文件/说明），
-- 不是题目答案。项目验收通过才能把相关概念推到 L4/L5。

CREATE TABLE projects (
  id TEXT PRIMARY KEY,                 -- '{pack_id}:{code}'
  pack_id TEXT NOT NULL REFERENCES packs(id),
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  brief TEXT NOT NULL DEFAULT '',      -- 一句话项目描述
  goal TEXT NOT NULL DEFAULT '',       -- 做完能证明什么能力
  authored_by TEXT NOT NULL DEFAULT 'content'
    CHECK (authored_by IN ('content','user')),  -- user = 学习者自己的真实项目
  repo_path TEXT,                      -- 可选：本地代码仓库路径
  created_at TEXT NOT NULL,
  UNIQUE (pack_id, code)
);
CREATE INDEX idx_projects_pack ON projects(pack_id);

-- 项目门禁：必须先把这些单元练到达标，才能开始提交本项目
CREATE TABLE project_requirements (
  project_id TEXT NOT NULL REFERENCES projects(id),
  unit_id TEXT NOT NULL REFERENCES course_units(id),
  min_level INTEGER NOT NULL DEFAULT 3 CHECK (min_level BETWEEN 1 AND 5),
  PRIMARY KEY (project_id, unit_id)
);

-- 里程碑：项目拆成的阶段，每个阶段有独立的验收标准
CREATE TABLE project_milestones (
  id TEXT PRIMARY KEY,                 -- '{project_id}:{code}'
  project_id TEXT NOT NULL REFERENCES projects(id),
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  objective TEXT NOT NULL DEFAULT '',
  sort_no REAL NOT NULL DEFAULT 0,
  est_minutes INTEGER NOT NULL DEFAULT 60,
  UNIQUE (project_id, code)
);

-- 交付物：里程碑要交的东西。acceptance 决定「怎么算通过」。
CREATE TABLE project_deliverables (
  id TEXT PRIMARY KEY,
  milestone_id TEXT NOT NULL REFERENCES project_milestones(id),
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('file','test','run','explain','data')),
  required INTEGER NOT NULL DEFAULT 1,
  acceptance_json TEXT NOT NULL DEFAULT '{}',
  --   file    : {"path":"main.py","min_bytes":200}
  --   test    : {"cmd":"python -m pytest -q","must_pass":true}
  --   run     : {"cmd":"python main.py","expect_exit":0,"expect_stdout_contains":"..."}
  --   explain : {"rubric":["..."],"min_items":2}   由 AI 按 rubric 评审
  --   data    : {"path":"result.json","jsonpath":"$.accuracy","min":0.8}
  sort_no REAL NOT NULL DEFAULT 0,
  UNIQUE (milestone_id, code)
);

-- 项目涉及的概念：项目验收通过后，这些概念获得 L4/L5 的证据
CREATE TABLE project_concepts (
  project_id TEXT NOT NULL REFERENCES projects(id),
  concept_id TEXT NOT NULL REFERENCES concepts(id),
  target_level INTEGER NOT NULL DEFAULT 4 CHECK (target_level BETWEEN 1 AND 5),
  PRIMARY KEY (project_id, concept_id)
);

-- ---------------------------------------------------------------- 证据
-- 提交一次交付物 = 一条不可变记录。失败也记录，失败本身就是学习证据。
CREATE TABLE deliverable_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deliverable_id TEXT NOT NULL REFERENCES project_deliverables(id),
  project_id TEXT NOT NULL REFERENCES projects(id),
  milestone_id TEXT NOT NULL REFERENCES project_milestones(id),
  artifact_path TEXT,                  -- 产物存放路径（相对 data/artifacts 或用户仓库）
  payload_json TEXT NOT NULL DEFAULT '{}',
  verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail','pending','skipped')),
  checks_json TEXT NOT NULL DEFAULT '[]',   -- 每项检查的结果与原始输出
  assisted INTEGER NOT NULL DEFAULT 0,      -- 1 = 借助提示/讲解完成
  submitted_at TEXT NOT NULL
);
CREATE INDEX idx_subm_project ON deliverable_submissions(project_id, submitted_at);

-- 里程碑状态投影
CREATE TABLE milestone_progress (
  milestone_id TEXT PRIMARY KEY REFERENCES project_milestones(id),
  status TEXT NOT NULL DEFAULT 'locked'
    CHECK (status IN ('locked','ready','in_progress','passed')),
  passed_at TEXT,
  updated_at TEXT NOT NULL
);

-- 项目状态投影
CREATE TABLE project_progress (
  project_id TEXT PRIMARY KEY REFERENCES projects(id),
  status TEXT NOT NULL DEFAULT 'locked'
    CHECK (status IN ('locked','available','in_progress','in_review','completed')),
  started_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL
);
