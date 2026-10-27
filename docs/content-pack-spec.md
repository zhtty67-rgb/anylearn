# 内容包协议规范（v1）

内容包（Content Pack）是 AnyLearn 唯一的领域注入点。框架代码不包含任何学科假设；
一个内容包目录放入 `content-packs/`，启动即自动安装，界面即变为该学科的学习系统。

## 目录约定

```
content-packs/<pack-id>/
├── pack.yaml                  # 必需：清单
├── data/
│   ├── knowledge_tree.json    # 可选：知识树（无则掌握度挂在模块级）
│   └── questions.jsonl        # 必需：题目，每行一个 JSON
└── assets/                    # 可选：图片等静态资源（题面 image_path 引用）
```

- 目录名以 `_` 或 `.` 开头会被跳过（`_template` 因此不会被安装）
- id 规则：`[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff_-]*`（小写字母/数字/中文起头）

## pack.yaml

| 字段 | 必需 | 说明 |
|---|---|---|
| `id` | ✓ | 包标识，全局唯一（缺省取目录名） |
| `name` | ✓ | 显示名（界面标题、模块卡头图） |
| `version` |  | 语义化版本，默认 1.0.0。**升级版本号后重装才会更新**；同版本幂等跳过 |
| `description` |  | 一句话介绍 |
| `modules[].id / name` | ✓ | 模块（顶层分区）；一级知识树节点必须声明在 modules 里 |
| `theme.primary_color` |  | 主题色，前端自动应用 |
| `ai.teacher_persona` |  | AI 教师人设提示词 |
| `grading.mode` |  | 预留（当前客观题自动判分） |
| `source` |  | 资料来源记录（kind/path/url） |

## knowledge_tree.json

节点数组，任意层级嵌套：

```json
[
  {
    "code": "module-a",            // 包内唯一
    "name": "模块甲",
    "module_id": "module-a",       // 仅一级节点需要，须在 modules 声明；子节点自动继承
    "description": "",
    "children": [
      { "code": "module-a-c1-p1", "name": "考点", "question_ids": ["q1", "q2"] }
    ]
  }
]
```

- 题目绑定方式二选一（可混用）：树节点 `question_ids`，或题目里的 `nodes: [code]`
- 升级时树里引用了已删除的题目 → 该绑定自动跳过（不报错）；题目里绑定了不存在的节点 → 报 422

## questions.jsonl

每行一题，`//` 开头的行是注释：

```json
{"id": "q1", "module": "module-a", "type": "single_choice",
 "stem": "题干（支持 **加粗**）", "options": ["甲", "乙", "丙", "丁"], "answer": "A",
 "explanation": "解析（支持 **加粗** 与换行）", "difficulty": 3, "estimated_seconds": 60,
 "tags": ["标签"], "nodes": ["module-a-c1-p1"], "image_path": "assets/fig1.png"}
```

| 字段 | 必需 | 说明 |
|---|---|---|
| `id` | ✓ | 全局唯一（建议带包前缀；与历史作答关联，**保持稳定**） |
| `module` | ✓ | 必须在 pack.yaml modules 中声明 |
| `type` | ✓ | `single_choice` / `multi_choice` / `cloze` / `short_answer` / `self_rate` |
| `stem` | ✓ | 题干 |
| `options` | 选择题必需 | ≥2 项 |
| `answer` | ✓ | 单选：字母 A-H；多选：至少两个字母如 `"ABC"`；填空/简答：文本（`a|b` 表示多个可接受答案）；自评卡：`good` |
| `explanation` |  | 解析，答后展示并进入 AI 讲解上下文 |
| `difficulty` |  | 1-5 |
| `estimated_seconds` |  | 预估用时，超时作对在 FSRS 中映射为 Hard |
| `tags` / `nodes` / `image_path` |  | 标签 / 知识节点绑定 / 配图 |

### 判分语义

- 单选：字母匹配，或直接输入正确选项内容（宽松归一化：忽略大小写/空白/标点）
- 填空：归一化后与任一可接受答案全等
- 简答：归一化后与任一可接受答案互为包含
- 自评卡：`good`/`easy` 记对；again/hard 记错，且自评词**直接**作为 FSRS 评分
- 空提交：允许正式提交（记录为未作答、判错、进入 FSRS 调度），不伪造答案

## 安装与升级行为

1. 启动时扫描 `content-packs/`（`ANYLEARN_AUTO_INSTALL=0` 可关闭），逐包安装
2. 同版本 → 跳过；高版本 → 全量刷新 modules/树/题目
3. 已被作答引用、但新包中移除的题目**保留**，保护 attempts/复习/掌握度历史
4. 安装后自动重建该包的 FSRS 与掌握度投影（确定性重放）
5. 手动：`POST /api/packs/install {"pack_id": "..."}`（强制重装）

## 从外部资料生成内容包

| 资料 | 工具 |
|---|---|
| Anki .apkg / 本机 collection.anki2 | `POST /api/import/anki`（自动转包并安装；牌组路径→知识树，Basic→自评卡，Cloze→填空） |
| JSONL 题库 | `POST /api/import/jsonl`（自动生成模块级知识树） |
| 任意语料（PDF/Markdown/词典…） | 参考 `scripts/build_pack_english_vocab.py`：两遍扫描（建池→出题），确定性干扰项与题号 |
