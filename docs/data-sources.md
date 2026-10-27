# 内容包数据来源与授权说明

本文档记录 `content-packs/` 下每个内容包的原始资料来源、加工方式与使用限制，
便于追溯与合规使用。

## ai-foundations · 人工智能基础

### 1. 人工智能训练师（三级）理论题库

| 项 | 内容 |
|---|---|
| 来源 | https://github.com/xxiao1127/AI_trainer- |
| 原始内容 | 300 判断题 + 300 单选题 + 300 多选题（含逐题解析） |
| 题库出处 | 国家职业技能标准 4-04-05-05「人工智能训练师」三级；素材源自上海交通大学终身教育学院 |
| 授权声明 | 仓库标注「免费开源，答案仅供参考，禁止商用或倒卖」；仓库未提供标准 OSI 许可证 |
| 加工方式 | 1) 与配套 `人工智能训练师三级理论答案.xlsx` 逐题交叉校验；2) **仅保留两源一致的题目**；3) 按能力域归入知识树章节 |
| 采用量 | 754 题（多选 300 全部一致；单选 283/300 一致；判断 172/300 一致，答案表有 126 项空缺） |
| 剔除量 | 33 题因两源答案冲突被剔除（宁缺毋滥） |

> ⚠️ 重要提示：题库原作者明确声明「官方未提供答案，本项目中的答案均为个人理解整理」。
> 本内容包已通过交叉校验剔除冲突项，但**答案仍仅供参考**，不构成官方答案。
> 因授权禁止商用，本内容包仅限个人学习使用。

### 2. MMLU 机器学习 / 计算机学科真题

| 项 | 内容 |
|---|---|
| 来源 | https://huggingface.co/datasets/cais/mmlu |
| 论文 | Measuring Massive Multitask Language Understanding (ICLR 2021) |
| 授权 | **MIT** |
| 采用学科 | machine_learning / college_computer_science / computer_security / high_school_computer_science / electrical_engineering |
| 采用量 | 557 题（英文四选一，官方答案） |
| 加工方式 | 原样转为框架题目协议，答案与选项不做改写 |

### 合计

1,311 题 = 754 道中文（AI 训练师，交叉校验）+ 557 道英文（MMLU 官方）。

知识树结构：

```
理论与职业认知 / 数据处理与标注 / 模型训练与评估
业务与智能应用 / 职业道德与安全 / 英文原版真题 MMLU
```

### 重建方式

原始数据与构建脚本缓存在 `.cache/ai-raw/`：

```powershell
cd .cache\ai-raw
python parse_md_bank.py     # 解析 Markdown 题库并与 xlsx 答案交叉校验
python build_ai_pack.py     # 生成 content-packs/ai-foundations
```

`build_ai_pack.py` 中的 `CHAPTERS` 关键词表决定了题目归入哪个能力域，
可据此调整知识树结构后重建。

---

## english-vocab · 英语词汇语义分类

| 项 | 内容 |
|---|---|
| 来源 | 本机《英语词义分类数据库（大学版）》（Obsidian 语义分类词库，放在用户主目录下的 `英语词义库/`） |
| 规模 | 1,464 个词组文件 / 29,447 个词条 |
| 加工方式 | 每个词条生成「词→义」「义→词」双选与例句填空；干扰项从同章节语义场确定性抽取 |
| 产物 | 81,199 题 / 50 个语义领域模块 / 1,641 个知识节点 |
| 构建脚本 | `scripts/build_pack_english_vocab.py` |
| **版权与分发限制** | **不得随仓库公开分发** |

> ⚠️ **版权说明**：该词库文本《英语词义分类全解》版权登记号「黔作登字-2022-A-00398574」，
> 作者声明「任何个人或机构均可免费使用，**但不得商用**」，并保留商业化后续版本的
> 全部权利。本仓库**只提供转换脚本，不包含该词库派生的题目数据**。
> 使用者需自备该词库并自行遵守其授权条款；如需分发本内容包，请先取得原作者许可。

## my-anki · 本机 Anki 收藏

| 项 | 内容 |
|---|---|
| 来源 | 本机 Anki 用户收藏库 `%APPDATA%\Anki2\账户 1\collection.anki2` |
| 加工方式 | 只读打开（不修改原库）；牌组路径 → 知识树，Basic → 自评卡，Cloze → 填空 |
| 产物 | 41 题 / 2 模块 |
| 工具 | `backend/app/importers/anki_apkg.py`（界面「内容包」页可直接导入） |

## 新增内容包的合规检查清单

1. 记录原始 URL、作者、许可证；
2. 若许可证不明或禁止商用，在本文档显著标注用途限制；
3. 涉及「非官方答案」的资料，尽量与第二来源交叉校验，冲突项剔除；
4. 不把受限资料的原始全文大段复制进仓库，只保留结构化题目与必要解析；
5. Anki 牌组导入时确认牌组本身的再分发许可。

---

## demo-ai-mmlu · MMLU 演示包（随仓库分发）

| 项 | 内容 |
|---|---|
| 来源 | https://huggingface.co/datasets/cais/mmlu |
| 论文 | Measuring Massive Multitask Language Understanding (ICLR 2021) |
| 授权 | **MIT**（可自由使用、修改、再分发） |
| 采用学科 | machine_learning / college_computer_science / computer_security / high_school_computer_science / electrical_engineering |
| 采用量 | 557 题（英文四选一，官方答案） |
| 构建脚本 | `scripts/build_demo_pack_mmlu.py`（`--fetch` 可自动下载） |

这是仓库内**唯一随代码分发的题库**，因为其许可允许再分发。
