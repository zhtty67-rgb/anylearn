-- 学习框架（Learning Framework）v1
--
-- 目的：在现有「知识树 + 题目 + 作答」之上，补出**教学过程**所需的结构。
--   课程(course) → 单元(unit) → 步骤(step) → 概念(concept)
-- 并记录：
--   - 概念先修关系（prerequisite），用于卡点定位与出题顺序
--   - 能力等级定级（L1..L5），由证据推导，不由模型随口给百分比
--   - 学习事件（learning_events），与 attempts 一样是不可变事实源
--
-- 设计约束：
--   1. 全部以 pack_id 隔离，框架本身不含任何领域内容。
--   2. 不修改既有表结构，只新增表；既有功能零回归。
--   3. 等级与掌握度都是「投影」，可由事件重放重建。

-- ---------------------------------------------------------------- 概念
-- 概念是教学的最小单位，比 knowledge_nodes 更贴近「一个可教可测的东西」。
-- 一个概念可以挂多个知识节点（兼容现有知识树），也可以独立存在。
CREATE TABLE concepts (
  id TEXT PRIMARY KEY,                 -- '{pack_id}:{code}'
  pack_id TEXT NOT NULL REFERENCES packs(id),
  code TEXT NOT NULL,
  module_id TEXT NOT NULL,
  name TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',    -- 一句话定义（费曼讲解的起点）
  misconceptions_json TEXT NOT NULL DEFAULT '[]',  -- 预设误解，供苏格拉底追问
  created_at TEXT NOT NULL,
  UNIQUE (pack_id, code)
);
CREATE INDEX idx_concept_pack ON concepts(pack_id);

-- 概念 ↔ 知识节点（可选映射，便于复用现有掌握度投影）
CREATE TABLE concept_node_map (
  concept_id TEXT NOT NULL REFERENCES concepts(id),
  node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
  PRIMARY KEY (concept_id, node_id)
);

-- ---------------------------------------------------------------- 先修
-- a 是 b 的先修：没学好 a，学 b 大概率卡住。
CREATE TABLE concept_prerequisites (
  concept_id TEXT NOT NULL REFERENCES concepts(id),
  prerequisite_id TEXT NOT NULL REFERENCES concepts(id),
  strength REAL NOT NULL DEFAULT 1.0,   -- 1.0 硬先修 / <1 软先修
  PRIMARY KEY (concept_id, prerequisite_id),
  CHECK (concept_id <> prerequisite_id)
);
CREATE INDEX idx_prereq ON concept_prerequisites(prerequisite_id);

-- ---------------------------------------------------------------- 课程
CREATE TABLE courses (
  id TEXT PRIMARY KEY,
  pack_id TEXT NOT NULL REFERENCES packs(id),
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  goal TEXT NOT NULL DEFAULT '',        -- 学完能独立做出什么
  audience TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '1.0.0',
  created_at TEXT NOT NULL,
  UNIQUE (pack_id, code)
);

CREATE TABLE course_units (
  id TEXT PRIMARY KEY,
  course_id TEXT NOT NULL REFERENCES courses(id),
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  objective TEXT NOT NULL DEFAULT '',   -- 本单元达成即可验收的能力
  sort_no REAL NOT NULL DEFAULT 0,
  est_minutes INTEGER NOT NULL DEFAULT 30,
  UNIQUE (course_id, code)
);

-- 单元 × 概念：单元覆盖哪些概念，以及目标是练到哪一级
CREATE TABLE unit_concepts (
  unit_id TEXT NOT NULL REFERENCES course_units(id),
  concept_id TEXT NOT NULL REFERENCES concepts(id),
  target_level INTEGER NOT NULL DEFAULT 3 CHECK (target_level BETWEEN 1 AND 5),
  role TEXT NOT NULL DEFAULT 'core' CHECK (role IN ('core','support','prereq')),
  PRIMARY KEY (unit_id, concept_id)
);

-- ---------------------------------------------------------------- 步骤
-- 学习闭环：诊断 → 讲解 → 追问 → 动手 → 验收 → 复习
CREATE TABLE unit_steps (
  id TEXT PRIMARY KEY,
  unit_id TEXT NOT NULL REFERENCES course_units(id),
  ord INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN
    ('diagnose','explain','socratic','feynman','practice','verify','review')),
  concept_id TEXT REFERENCES concepts(id),
  title TEXT NOT NULL DEFAULT '',
  content_ref TEXT,                     -- 指向教材页码/文件，如 'E:/AI教学资料/x.pdf#p123'
  config_json TEXT NOT NULL DEFAULT '{}',  -- 题量/提示预算/评分标准等
  UNIQUE (unit_id, ord)
);

-- ---------------------------------------------------------------- 证据
-- 学习事件：与 attempts 并列的不可变事实源。
-- 不复用 attempts 的原因：attempts 是「答题」事件，这里是「教学过程」事件
-- （看了讲解、用了提示、完成了讲解任务、通过验收…），语义不同。
CREATE TABLE learning_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_id TEXT NOT NULL REFERENCES packs(id),
  session_id TEXT,
  unit_id TEXT,
  step_id TEXT,
  concept_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN
    ('step_viewed','hint_used','self_explain','attempt','verify_pass','verify_fail','misconception_hit',
     'project_pass','project_fail')),
  hint_level INTEGER NOT NULL DEFAULT 0,
  assisted INTEGER NOT NULL DEFAULT 0,   -- 1 = 借助提示/讲解完成，不能算独立完成
  payload_json TEXT NOT NULL DEFAULT '{}',
  occurred_at TEXT NOT NULL
);
CREATE INDEX idx_le_concept ON learning_events(concept_id, occurred_at);
CREATE INDEX idx_le_unit ON learning_events(unit_id, occurred_at);

-- 能力定级投影（由 learning_events + attempts 重放得到，可随时重建）
CREATE TABLE concept_ability (
  concept_id TEXT PRIMARY KEY REFERENCES concepts(id),
  level INTEGER NOT NULL DEFAULT 0 CHECK (level BETWEEN 0 AND 5),
  best_independent_level INTEGER NOT NULL DEFAULT 0,
  independent_passes INTEGER NOT NULL DEFAULT 0,  -- 无提示独立通过的次数
  assisted_passes INTEGER NOT NULL DEFAULT 0,
  failures INTEGER NOT NULL DEFAULT 0,
  misconception_hits INTEGER NOT NULL DEFAULT 0,
  last_evidence_at TEXT,
  updated_at TEXT NOT NULL
);

-- 单元进度
CREATE TABLE unit_progress (
  unit_id TEXT PRIMARY KEY REFERENCES course_units(id),
  status TEXT NOT NULL DEFAULT 'locked'
    CHECK (status IN ('locked','available','in_progress','completed','mastered')),
  current_step INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL
);
