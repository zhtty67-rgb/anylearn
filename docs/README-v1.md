# AnyLearn 学习系统 v1 总览

本文件是规划全部落地后的收口文档。**92 个测试全部通过**，题库按用户要求暂缓、未做。

## 一、整体架构

```
框架（不含任何学科内容）          内容包（学科注入）
├─ 学习框架 lesson      ←──     data/curriculum.json
├─ 项目层   project     ←──     data/projects.json
├─ AI 教师  tutor       ←──     pack.yaml: teacher_persona
└─ 评审器   reviewer
```

三层递进，各有明确职责：

| 层 | 回答的问题 | 证据来源 | 上限 |
|---|---|---|---|
| lesson | 这个**知识点**你会不会 | 做题、讲解、追问 | L4 |
| project | 你能不能**独立做出真东西** | 产物验收 | L5 |
| tutor / reviewer | 帮你讲清 / 判断讲清没有 | **不给等级** | — |

## 二、三条贯穿全局的设计铁律

### 1. 等级只由证据推导

- `/api/learn/events` 刻意**不接收 `level` 字段**
- 做题最多到 L4，**L5 必须由项目验收兑现**（`project_pass` 事件）
- `hint_level > 0` 只计辅助通过，**不推进等级**

### 2. 模型不判定学习者过没过

- AI 教师可以追问、可以指出漏洞，但**不能写等级**
- 评审器要求模型**逐条给 rubric 判定 + 引用原文的理由**，不接受总分
- 模型结论与逐条判定冲突时，**以逐条判定为准**
- 模型少给判定条数 → `unclear`，**不能算通过**
- **provider 是 mock 时，结论永远降级为 pending/unclear**——离线占位符没有判断资格

### 3. 事实源不可变

- `attempts` / `learning_events` / `deliverable_submissions` 只追加
- 评审写**新的提交记录**，不改原记录
- 掌握度、能力等级、里程碑、项目状态全是**可重放投影**
- 重装内容包刷新结构，但**不清学习事件、不删用户项目**

## 三、L1–L5 定级规则

| 等级 | 含义 | 达成条件 |
|---|---|---|
| L0 | 未接触 | 无事件 |
| L1 识别 | 能分辨 | ≥1 次独立通过 |
| L2 解释 | 能说清 | L1 + 1 次非辅助 `self_explain` |
| L3 应用 | 提示下能完成 | L2 + ≥2 次独立通过 |
| L4 诊断 | 能定位问题 | L3 + ≥3 次独立通过 + 0 次误解命中 |
| L5 迁移 | 陌生场景成立 | L4 + 非辅助验收 + ≥4 次独立通过 |

## 四、项目层：验收的是产物，不是答案

五种交付物，各有机器可判的规则：

| kind | 判定方式 |
|---|---|
| `file` | 存在 + 字节数 + 路径越界拒绝 |
| `test` | 跑测试，退出码 0 |
| `run` | 退出码 + stdout 关键字 |
| `data` | JSON + jsonpath + 数值比较 |
| `explain` | 结构检查 + **语义走评审** |

### 三态验收（踩出来的）

| verdict | 含义 | 算里程碑通过？ |
|---|---|---|
| `pass` | 机器可判且通过 | 是 |
| `fail` | 结构/执行未通过 | 否 |
| `pending` | 结构合格，等评审 | **否**（状态显示 `in_review`） |

## 五、内容包协议

| 文件 | 作用 | 必需 |
|---|---|---|
| `pack.yaml` | 元信息、模块、`teacher_persona` | 是 |
| `data/knowledge_tree.yaml` | 知识点树 | 否 |
| `data/questions/*.jsonl` | 题库 | 否（本次暂缓） |
| `data/curriculum.json` | 概念、先修、课程、单元、步骤 | 否 |
| `data/projects.json` | 项目、门禁、里程碑、交付物 | 否 |

**页码来源**：示范内容的所有 `content_ref` 页码，都是在该 PDF 内检索原文关键词定位的
（p41/p43/p44/p47 过拟合；p154/p156 混淆矩阵与 ROC；p184/p185/p189 交叉验证；p211/p221/p222 收缩），不是估算。

## 六、示范内容：`content-packs/ai-learning-framework`

- **10 个概念**，先修链完整（train-test-split → generalization → overfitting → bias-variance；validation-set + bias-variance → cross-validation）
- **4 个单元**，25 个步骤，全部按「诊断 → 追问 → 讲解 → 费曼 → 动手 → 验收」闭环
- **3 个项目**：拟合诊断报告 / 交叉验证选模型 / 不平衡数据评估

## 七、接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/packs/{id}/courses` | 课程与单元 + 进度 |
| GET | `/api/packs/{id}/projects` | 项目列表 + 门禁 + 状态 |
| GET | `/api/courses/{id}/next` | 当前该学的单元 |
| GET | `/api/units/{id}` | 步骤 + 概念等级 + 卡点 |
| POST | `/api/learn/steps/done` | 标记步骤完成 |
| POST | `/api/learn/events` | 记录学习证据（**不收 level**） |
| GET | `/api/concepts/{id}/diagnose` | 卡点诊断 |
| GET | `/api/projects/{id}` | 项目详情 |
| GET | `/api/projects/{id}/pending` | 待评审提交 |
| POST | `/api/projects` | 登记用户自建项目 |
| POST | `/api/deliverables/{id}/submit` | 提交产物验收 |
| POST | `/api/submissions/review` | 人工评审 |
| POST | `/api/submissions/ai-review` | AI 教师评审 |
| POST | `/api/tutor/socratic` | 苏格拉底追问 |
| POST | `/api/tutor/feynman-review` | 费曼讲解评审 |

## 八、前端

零构建 SPA，新增两个页面（`learn.js` + `learn.css`，挂到既有路由）：

- **学习路径** `#/learn`：课程 → 单元 → 进度
- **单元详情** `#/unit?id=…`：概念等级、卡点、教学步骤、追问与费曼工具
- **卡点诊断** `#/diagnose?id=…`：为什么卡住 + 下一步
- **项目** `#/projects` / `#/project?id=…`：里程碑、交付物验收、待评审区

## 九、测试

**92 passed**，分模块：

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_migrations.py` 等既有 | 36 | 原有功能零回归 |
| `test_lesson.py` | 12 | 定级阶梯、辅助不升级、幂等重建 |
| `test_curriculum.py` | 12 | 课程/项目装载、非法输入、重装保留 |
| `test_learning_flow.py` | 2 | 端到端教学闭环 |
| `test_project.py` | 17 | 门禁、五类交付物、三态、等级联动 |
| `test_ai_teacher.py` | 12 | 逐条评审、冲突处理、mock 契约、追问不给等级 |

## 十、必须说清的局限

1. **真实模型未接入**：默认配置是 mock。所有 AI 能力在 mock 下都**明确降级**（追问返回通用问题、评审返回 unclear），不会假装能判断。接入真实模型只需配 `model_config.toml` 或 `AI_BASE_URL`/`AI_API_KEY`。
2. **`test`/`run` 会真的执行命令**：内容包里的命令属可信输入；来源不明的内容包不要装。
3. **题库未做**：按用户要求暂缓。`ai-foundations` 包 1311 题挂载知识点为 0 的缺陷仍在。
4. **对外发布的版权问题未解**：AI 训练师题目禁止商用；157 份 PDF 不得随产品分发；AnyLearn 无 LICENSE。
5. **只有 1 门课**：结构完整但内容量仍是示范级。
