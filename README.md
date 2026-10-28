# AnyLearn —— 注入式通用 AI 学习框架

> 从公考智能备考系统（`gongkao-learning-os`）的工程经验中抽取的**内容无关纯学习框架**，
> 遵循 **灵枢（Lingshu）** 生态的设计理念。
> 框架本身不带任何学科内容：**注入什么内容包，就变成什么学习系统。**

同一套框架，换一个内容包就换一个学科：

| 注入的内容包 | 变成 | 规模 |
|---|---|---|
| 英语语义分类词库 | 英语词汇学习系统 | 81,199 题 / 50 语义领域 |
| 人工智能训练师题库 + MMLU | 人工智能基础学习系统 | 1,311 题 / 6 模块 |
| 任意 Anki 牌组 / JSONL 题库 | 你自己的学科 | 取决于数据源 |

> **本仓库只附带可自由分发的 MMLU 演示题库（MIT）**，不含版权受限的第三方语料
> （版权说明见 [`ECOSYSTEM.md`](ECOSYSTEM.md) 与 [`docs/data-sources.md`](docs/data-sources.md)）。
> 克隆后即可体验完整学习闭环；想换学科，自备数据后用脚本或界面导入。

## 一分钟跑起来

```powershell
cd <本仓库目录>
powershell -File scripts\start-backend.ps1        # 首次自动建 venv、装依赖
# 浏览器打开 http://127.0.0.1:8000
```

启动时自动完成：数据库迁移 → 扫描 `content-packs/` → 安装/升级全部内容包。

### 开箱即用的内容

克隆后各内容包**不含第三方题库**，但开箱即可完整使用：

| 内容包 | 说明 |
|---|---|
| `_template` | 协议模板 + 3 道示例题，演示 5 种题型的写法 |
| `demo-ai-mmlu` | **MMLU 机器学习/计算机真题 557 题**（MIT 许可，可自由分发） |

启动后右上角切换内容包，即可走完「组题 → 作答 → 判分 → 复习调度 →
掌握度 → 知识树 → AI 教师」全流程。

想换学科，自备数据用 `scripts/build_demo_pack_mmlu.py` 或
`scripts/build_pack_english_vocab.py` 的模式生成，界面也可直接导入 Anki / JSONL。

### 想接入 AI 教师

默认使用离线 mock（不联网即可完整体验）。接真实模型二选一：

1. 编辑 `model_config.toml` 填写 `base_url` 与 `api_key`
2. 或设环境变量 `AI_BASE_URL` / `AI_API_KEY`

## 目录结构

```
anylearn/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口（迁移+自动装包+静态托管）
│   │   ├── db.py                # sqlite3 + 版本化 SQL 迁移引擎（移植自公考）
│   │   ├── migrations/          # 001_init / 002_multi_choice
│   │   ├── contentpack/loader.py# ★ 内容包协议与安装器（框架的注入点）
│   │   ├── domain/              # 领域无关引擎（全部由作答投影重建）
│   │   │   ├── quiz.py          #   组题/判分（5题型通用判分，空提交语义）
│   │   │   ├── review.py        #   FSRS-6 间隔重复（py-fsrs 6.3.2，自动评分映射）
│   │   │   ├── mastery.py       #   掌握度投影（提示打折 + 拉普拉斯平滑）
│   │   │   └── analytics.py     #   概览统计
│   │   ├── ai/                  # LLM 网关（FAST/BALANCED/STRONG 三档，移植自公考）
│   │   │   ├── gateway.py       #   mock / openai_compatible 双 provider
│   │   │   └── teacher.py       #   AI 教师：人设由内容包注入，hint不泄答案
│   │   ├── importers/           # ★ 开源社区资料导入器
│   │   │   ├── anki_apkg.py     #   Anki .apkg / 裸 .anki2 收藏库（新旧schema+cloze）
│   │   │   └── jsonl_import.py  #   任意 JSONL 题库
│   │   ├── routers/api.py       # 全部 REST 路由
│   │   └── static/              # 前端 SPA（零构建，纯 HTML/JS/CSS）
│   └── tests/                   # 79 个 pytest（协议/引擎/导入/API/教学/项目 全链路）
├── content-packs/               # ★ 内容包目录（放进来即自动安装）
│   ├── _template/               # 协议模板 + 3 道示例题，开箱即用
│   └── demo-ai-mmlu/            # MMLU 演示题库 557 题（MIT，可自由分发）
├── scripts/
│   ├── build_demo_pack_mmlu.py      # MMLU → 演示内容包（MIT，可复现）
│   ├── build_pack_english_vocab.py  # 词义库→内容包构建脚本（任意语料转换参考）
│   ├── smoke_e2e.py                 # 端到端冒烟
│   ├── package_release.py           # 脱敏打包 + 自检
│   └── start-backend.ps1
├── docs/
│   ├── content-pack-spec.md     # 内容包协议规范
│   └── data-sources.md          # 各数据来源与授权说明
├── ECOSYSTEM.md                 # 灵枢生态署名与内容声明
├── LICENSE                      # MIT
└── model_config.toml            # 模型网关配置（三档策略）
```

> `data/anylearn.db` 不入库：首次启动自动创建并迁移。

## 内容包协议（注入即变系统）
一个内容包 = 一个目录，详见 [`docs/content-pack-spec.md`](docs/content-pack-spec.md)：

```
content-packs/<pack-id>/
├── pack.yaml                 # 清单：名称/版本/模块/主题色/AI教师人设
├── data/knowledge_tree.json  # 知识树：模块 > 章节 > 考点（可无限层级）
└── data/questions.jsonl      # 题目：每行一题
└── assets/                   # 可选图片等资源
```

题目协议支持 4 种题型，全部由通用判分器处理：

| type | answer 含义 | 判分 |
|---|---|---|
| `single_choice` | 选项字母 A-H | 字母或选项内容匹配 |
| `multi_choice` | 至少两个选项字母，如 `"ABC"` | 必须完全一致，少选/多选均判错 |
| `cloze` | 文本，`a|b` 多答案 | 宽松归一化精确匹配 |
| `short_answer` | 文本，`a|b` 多答案 | 包含式匹配 |
| `self_rate` | 自评卡（Anki式） | again/hard/good/easy，直通 FSRS 评分 |

**升级安全**：版本号升级后重装会全量刷新内容，但已被作答引用的旧题保留，
attempts / FSRS 卡片 / 掌握度历史不受破坏（作答是不可变事实源，一切投影可重放重建——公考系统的核心原则）。

## 从开源社区获取学习资料

| 来源 | 方式 |
|---|---|
| **AnkiWeb shared decks**（数万开放牌组） | 下载 .apkg → 界面"内容包"页填路径导入 |
| **本机 Anki 收藏** | 直接填 `collection.anki2` 路径（只读导入，不锁原库） |
| **HuggingFace 基准数据集**（MMLU 等） | 下载 parquet/JSON → 写成 JSONL 导入 |
| **GitHub 开放题库**（如人工智能训练师题库） | clone 后按 JSONL 导入，或写转换脚本 |
| **开放词典/教材**（ECDICT、CS-Notes 等） | 写成 JSONL → 界面导入或 `POST /api/import/jsonl` |
| **自有语料** | 参考 `scripts/build_pack_english_vocab.py` 的两遍转换模式 |

> 各来源的授权与加工细节见 [`docs/data-sources.md`](docs/data-sources.md)。
> **本仓库不附带任何第三方题库数据**，只提供导入器与转换脚本；
> 使用前请核对各来源的许可条款，尤其是「不得商用」类声明。

## AI 教师

- 人设来自内容包 `ai.teacher_persona`，学科上下文自动注入
- 三种模式：`hint`（答前提示，系统级禁止泄露答案）、`explain`（答后讲解）、`chat`（自由追问）
- 模型配置：`model_config.toml`（三档策略）+ 环境变量 `AI_BASE_URL` / `AI_API_KEY`；
  未配置或端点失效时自动回落离线 mock（结果标记 `mock-degraded`），学习流程不中断

## 教学过程与项目验收

题库之上还有两层，回答「该学什么、卡在哪、凭什么说你会了」：

**Lesson 层（迁移 `003`）** — 课程 course → 单元 unit → 步骤 step → 概念 concept。
步骤走「诊断 → 苏格拉底追问 → 讲解 → 费曼讲解 → 动手 → 独立验收」，
概念之间记录先修关系用于卡点定位。

**Project 层（迁移 `004`）** — 项目 project → 门禁 → 里程碑 → 交付物。
交付物按规则自动验收（文件存在性、命令退出码、数据校验、解释评审），
通过后才会把证据写回概念等级。

核心规则：

> **能力等级只能由证据推导，模型不能直接给分。**
> 纯做题最高到 L4；**L5 必须由项目验收兑现**。
> 辅助完成（`assisted`）会记账但不计入独立验收证据。

细节见 [`docs/learning-framework.md`](docs/learning-framework.md) 与
[`docs/project-layer.md`](docs/project-layer.md)。

## 界面

**与公考 Learning OS 共用同一套设计语言**（直接沿用其 `globals.css` 体系）：
米白底 `#f5f4ef`、墨绿主色 `#296044`、92px 顶栏 + 下划线导航、`eyebrow + h1` 引导头、
`card-top` 卡片头、`workspace + 侧栏 note` 双栏、答题卡 chips、三档信心度 fieldset、
选项选中/正确/错误三态配色、掌握度渐变进度条。

内容包可在 `theme.primary_color` 覆盖主色（例如换学科品牌色），不填则默认沿用公考墨绿。

## 核心 API

```
GET  /api/packs                        已安装内容包
POST /api/packs/install                安装/升级（可指定 pack_id）
POST /api/import/anki                  导入 .apkg / .anki2
POST /api/import/jsonl                 导入 JSONL 题库
POST /api/quiz/sessions                组题 {pack_id, module_ids, count, mode: practice|review}
GET  /api/quiz/sessions/{id}           题目列表（不泄答案）
POST /api/quiz/sessions/{id}/answers   提交（confidence 可选三档；空答案=正式未作答）
GET  /api/review/due?pack_id=          FSRS 到期卡片
GET  /api/packs/{id}/tree              知识树+掌握度
GET  /api/packs/{id}/overview          学习概览
POST /api/ai/teacher                   AI 教师 {mode: hint|explain|chat}

# 教学过程（lesson 层）
GET  /api/packs/{id}/courses           课程列表
GET  /api/courses/{id}/next            下一个该学的单元
GET  /api/units/{id}                   单元状态与步骤进度
GET  /api/concepts/{id}/diagnose       卡点诊断（含先修缺口）

# 项目验收（project 层）
GET  /api/packs/{id}/projects          项目列表
GET  /api/projects/{id}                项目状态与里程碑
POST /api/deliverables/{id}/submit     提交交付物（自动验收）
```

## 测试与验证

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests -q      # 36 passed
..\.venv\Scripts\python ..\scripts\smoke_e2e.py # 需先启动服务；端到端检查
```

## 发布打包

```powershell
python scripts\package_release.py            # 生成 release/anylearn-<时间戳>/ 与同名 zip
python scripts\package_release.py --no-zip   # 只出目录
```

打包会脱敏（清空 api_key/base_url）、清空全部个人学习记录、移除个人与第三方内容包、
排除本机缓存，并自检包内无密钥、无本机绝对路径。细节见脚本头部说明；
发布给他人时的注意事项见 [`RELEASE_NOTES.md`](RELEASE_NOTES.md)。

## 从公考系统继承了什么

| 资产 | 来源 | 去领域化处理 |
|---|---|---|
| FSRS 复习投影 | `gongkao-learning-os/backend/app/domain/review.py` | 按 pack 重建；新增 self_rate 直通评分 |
| 掌握度投影 | `.../domain/mastery.py` | 同上 |
| 迁移引擎 | `.../db.py` | 通用化（去掉历史特例） |
| AI 网关三档策略 | `.../ai/gateway.py + config.py` | 裁剪视觉/回退分支，保留 schema 校验与截断重试 |
| 作答不可变+投影重建 | 公考数据一致性原则 | attempts 为唯一事实源 |
| 空答案正式提交 / 三档信心 | 公考 v034 语义 | confidence 纯可选，空提交判错并进复习 |
| 提示不泄答案 | 引导复盘红线 | hint 模式系统提示词强制 |

刻意**未搬**的：申论批改全家桶、模块→名师硬编码映射、题库导入修复管线——这些是公考领域内容，不属于纯框架。

## 生态署名

本项目遵循 **灵枢（Lingshu）** 生态：

- **灵枢生态** — 「灵 × 脑 × 身」AI 生命载体聚合仓 · https://github.com/FuRongJun-1999/lingshu
- **dsh-memory（脑）** — 白箱认知图引擎 · https://github.com/FuRongJun-1999/dsh-memory
- **DeepSeek-Harness（DSH）** — 插件宿主框架 · https://github.com/deepseek-ai/deepseek-harness

承袭的核心约定：作答是不可变事实源、能力等级只由证据推导、教学复盘不污染统计、
提示不泄答案。完整署名与内容声明见 [`ECOSYSTEM.md`](ECOSYSTEM.md)。

## 许可

框架代码 [MIT](LICENSE)。随仓库的演示题库为 MMLU（MIT）。
其他第三方资料的授权见 [`docs/data-sources.md`](docs/data-sources.md)，
其中明确标注了「不得商用」类限制——请勿将受限内容包用于商业用途或再分发。
