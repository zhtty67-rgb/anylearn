-- AnyLearn 初始结构：内容包 / 知识树 / 题目 / 作答 / 复习 / 掌握度 / AI会话
-- 全部数据以 pack_id 隔离，框架本身不包含任何领域内容。

CREATE TABLE packs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  manifest_json TEXT NOT NULL,
  installed_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE modules (
  pack_id TEXT NOT NULL REFERENCES packs(id),
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  sort_no REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (pack_id, id)
);

CREATE TABLE knowledge_nodes (
  id TEXT PRIMARY KEY,               -- '{pack_id}:{code}'
  pack_id TEXT NOT NULL REFERENCES packs(id),
  code TEXT NOT NULL,
  module_id TEXT NOT NULL,
  parent_id TEXT REFERENCES knowledge_nodes(id),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  weight REAL NOT NULL DEFAULT 1.0,
  level INTEGER NOT NULL,
  sort_no REAL NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (pack_id, code)
);
CREATE INDEX idx_kn_pack ON knowledge_nodes(pack_id);
CREATE INDEX idx_kn_module ON knowledge_nodes(pack_id, module_id);

CREATE TABLE questions (
  id TEXT PRIMARY KEY,
  pack_id TEXT NOT NULL REFERENCES packs(id),
  module_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('single_choice','cloze','self_rate','short_answer')),
  stem TEXT NOT NULL,
  options_json TEXT NOT NULL DEFAULT '[]',
  answer TEXT NOT NULL,
  explanation TEXT NOT NULL DEFAULT '',
  difficulty INTEGER NOT NULL DEFAULT 3 CHECK (difficulty BETWEEN 1 AND 5),
  estimated_seconds INTEGER NOT NULL DEFAULT 60,
  image_path TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX idx_q_pack_module ON questions(pack_id, module_id);

CREATE TABLE question_node_map (
  question_id TEXT NOT NULL REFERENCES questions(id),
  node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
  weight REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (question_id, node_id)
);
CREATE INDEX idx_qnm_node ON question_node_map(node_id);

CREATE TABLE quiz_sessions (
  id TEXT PRIMARY KEY,
  pack_id TEXT NOT NULL REFERENCES packs(id),
  mode TEXT NOT NULL DEFAULT 'practice' CHECK (mode IN ('practice','review')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','finished','abandoned')),
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE session_questions (
  session_id TEXT NOT NULL REFERENCES quiz_sessions(id),
  question_id TEXT NOT NULL REFERENCES questions(id),
  ord INTEGER NOT NULL,
  PRIMARY KEY (session_id, question_id)
);

-- 作答是不可变事实源；复习卡片与掌握度均由其投影重建。
CREATE TABLE attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id TEXT NOT NULL REFERENCES questions(id),
  session_id TEXT REFERENCES quiz_sessions(id),
  answer TEXT,
  correct INTEGER NOT NULL,
  confidence REAL,
  hint_level INTEGER NOT NULL DEFAULT 0,
  elapsed_ms INTEGER NOT NULL DEFAULT 0,
  valid_for_stats INTEGER NOT NULL DEFAULT 1,
  raw_json TEXT NOT NULL DEFAULT '{}',
  submitted_at TEXT NOT NULL
);
CREATE INDEX idx_att_q ON attempts(question_id, submitted_at);

CREATE TABLE review_events (
  id TEXT PRIMARY KEY,
  attempt_id INTEGER NOT NULL REFERENCES attempts(id),
  question_id TEXT NOT NULL,
  rating INTEGER NOT NULL,
  rating_reason TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  elapsed_ms INTEGER NOT NULL,
  state_before INTEGER NOT NULL,
  state_after INTEGER NOT NULL,
  due_before TEXT,
  due_after TEXT NOT NULL,
  stability_after REAL NOT NULL,
  difficulty_after REAL NOT NULL,
  created_at TEXT NOT NULL,
  scheduler_version TEXT NOT NULL,
  rating_policy_version TEXT NOT NULL
);
CREATE INDEX idx_re_q ON review_events(question_id);

CREATE TABLE review_cards (
  question_id TEXT PRIMARY KEY,
  card_id INTEGER NOT NULL,
  state INTEGER NOT NULL,
  step INTEGER NOT NULL DEFAULT 0,
  stability REAL NOT NULL,
  difficulty REAL NOT NULL,
  due TEXT NOT NULL,
  last_review TEXT,
  review_count INTEGER NOT NULL,
  lapse_count INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE mastery_evidence (
  attempt_id INTEGER NOT NULL REFERENCES attempts(id),
  knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
  success_evidence REAL NOT NULL,
  failure_evidence REAL NOT NULL,
  time_ratio REAL NOT NULL,
  timed INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (attempt_id, knowledge_node_id)
);

CREATE TABLE mastery_state (
  knowledge_node_id TEXT PRIMARY KEY REFERENCES knowledge_nodes(id),
  mastery_score REAL NOT NULL,
  positive_evidence REAL NOT NULL,
  negative_evidence REAL NOT NULL,
  evidence_count INTEGER NOT NULL,
  recent_accuracy REAL,
  timed_accuracy REAL,
  mean_time_ratio REAL,
  hint_dependency REAL NOT NULL DEFAULT 0,
  last_attempt_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE ai_conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_id TEXT NOT NULL,
  question_id TEXT,
  mode TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_aic ON ai_conversations(pack_id, question_id);
