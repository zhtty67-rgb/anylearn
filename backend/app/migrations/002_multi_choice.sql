-- 新增多选题型：放宽 questions.type 的 CHECK 约束
-- SQLite 不支持修改 CHECK，需重建表；数据按原样搬运。
PRAGMA foreign_keys=OFF;

CREATE TABLE questions_new (
  id TEXT PRIMARY KEY,
  pack_id TEXT NOT NULL REFERENCES packs(id),
  module_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('single_choice','multi_choice','cloze','self_rate','short_answer')),
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

INSERT INTO questions_new
  (id, pack_id, module_id, type, stem, options_json, answer, explanation,
   difficulty, estimated_seconds, image_path, tags_json, created_at)
SELECT id, pack_id, module_id, type, stem, options_json, answer, explanation,
       difficulty, estimated_seconds, image_path, tags_json, created_at
FROM questions;

DROP TABLE questions;
ALTER TABLE questions_new RENAME TO questions;
CREATE INDEX idx_q_pack_module ON questions(pack_id, module_id);

PRAGMA foreign_keys=ON;
