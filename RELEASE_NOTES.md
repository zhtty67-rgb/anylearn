# AnyLearn 发布说明

## 这是什么

AnyLearn 是一个**注入式通用学习框架**：框架本身不含任何学科内容，放入一个「内容包」
就变成对应领域的学习系统。内置间隔重复（FSRS）、掌握度投影、AI 教师与开源资料导入。

## 版本信息

| 项 | 值 |
|---|---|
| 打包时间 | 见 `RELEASE_MANIFEST.json` |
| 随包内容包 | `english-vocab`（81,199 题）、`ai-foundations`（1,311 题） |
| 后端 | Python + FastAPI + SQLite（原生 sqlite3，无 ORM） |
| 前端 | 零构建 SPA（纯 HTML/CSS/JS，由后端托管） |

## 快速开始

需要 Python 3.10+。

```powershell
cd <解压目录>
powershell -File scripts\start-backend.ps1
# 浏览器打开 http://127.0.0.1:8000
```

首次启动会自动创建虚拟环境、安装依赖、执行数据库迁移，并扫描 `content-packs/`
安装内容包。也可以双击 `启动学习系统.bat`。

## 配置 AI 教师

默认使用离线 mock（不联网，可完整体验流程）。接入真实模型有两种方式：

1. 编辑 `model_config.toml`，填写各档位的 `base_url` 与 `api_key`
2. 或设置环境变量 `AI_BASE_URL` / `AI_API_KEY`

三档策略：`FAST`（答前提示）、`BALANCED`（讲解/问答）、`STRONG`（生成/评分）。

## 包内包含与不包含

**包含**：全部框架代码、测试、两个公开内容包、内容包协议文档、数据来源说明。

**不包含**（发布时已脱敏/排除）：

- 任何 API 密钥、模型端点（`model_config.toml` 中的 `base_url`/`api_key` 已清空）
- 全部个人学习记录（作答、复习卡片、掌握度、AI 对话已清空，`VACUUM` 整理）
- 本机缓存与原始资料（`.cache/`、`.venv/`）
- 个人 Anki 收藏导入的内容包
- 非本仓库产出的第三方内容包草案

## 内容包授权提示

- **english-vocab**：基于本机英语词义分类词库构建，请自行确认原始词库的使用条款。
- **ai-foundations**：由人工智能训练师（三级）题库（GitHub `xxiao1127/AI_trainer-`，
  禁止商用、答案仅供参考）与 MMLU（MIT）合成。训练师题库部分已与配套答案表交叉校验、
  剔除冲突项，**答案仅供参考，仅限个人学习使用**。

详见 `docs/data-sources.md`。

## 常用命令

```powershell
# 测试
cd backend
..\.venv\Scripts\python -m pytest tests -q

# 端到端冒烟（需先启动服务）
..\.venv\Scripts\python ..\scripts\smoke_e2e.py

# 重新打包（含脱敏与自检）
python scripts\package_release.py
```

## 自定义内容包

协议见 `docs/content-pack-spec.md`。最小结构：

```
content-packs/<pack-id>/
├── pack.yaml
└── data/
    ├── knowledge_tree.json
    └── questions.jsonl
```

支持 5 种题型：`single_choice` / `multi_choice` / `cloze` / `short_answer` / `self_rate`。
放入目录后重启即自动安装；界面「内容包」页也可直接导入 Anki 牌组或 JSONL 题库。
