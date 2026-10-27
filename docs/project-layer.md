# 项目层（Project Layer）v1

回答学习者第一个问题：**「这个项目制的学习方法接进去了吗？」**
——在 v1 之前，答案是没有。现在接进去了。

## 一、它和学习框架的真实分工

| 层 | 回答的问题 | 证据来源 |
|---|---|---|
| lesson 层（003） | 这个**知识点**你会不会？ | 做题、讲解、追问 |
| project 层（004） | 你能不能**独立做出真东西**？ | 产物验收 |

一句话规则：**只在 lesson 层做得好，最高到 L4；L5 必须由项目验收兑现。**

这不是设计洁癖，而是项目层存在的唯一理由。如果做题能拿到最高级，项目层就是装饰。

## 二、数据模型（`004_project_layer.sql`）

```
项目 project ──门禁──> 单元（先修，必须先练到达标）
    │
    ├── 里程碑 milestone
    │      └── 交付物 deliverable ──验收规则──> 一个可判定的结论
    │
    └── 概念映射 ──验收通过──> 概念等级 L4/L5

提交记录 deliverable_submissions（不可变）
```

| 表 | 作用 |
|---|---|
| `projects` | `authored_by='content'`（内容包提供）或 `'user'`（学习者自己的真实项目） |
| `project_requirements` | 门禁：必须先练到达标的单元 + `min_level` |
| `project_milestones` | 项目阶段，各自独立验收 |
| `project_deliverables` | 要交的产物 + `acceptance` 判定配置 |
| `deliverable_submissions` | 每次提交（含失败）——失败也是学习证据 |
| `project_concepts` | 项目验收通过后，这些概念获得 L4/L5 |

## 三、五种交付物与判定方式

| kind | 判定方式 | 例子 |
|---|---|---|
| `file` | 文件存在 + 字节数达标 + 禁止路径越界 | `{"path":"main.py","min_bytes":200}` |
| `test` | 跑测试，退出码为 0 | `{"cmd":"python -m pytest -q"}` |
| `run` | 跑命令，退出码 + stdout 关键字 | `{"cmd":"python main.py","expect_stdout_contains":"result.json"}` |
| `data` | 读 JSON，按 jsonpath 检查数值 | `{"path":"result.json","jsonpath":"$.accuracy","min":0.8}` |
| `explain` | 结构检查（字数）；**语义交评审** | `{"min_chars":120,"rubric":["..."]}` |

**为什么 `explain` 不自动判对错**：让模型给一段解释打分，等于回到「模型随便给分」的老问题。框架只做结构检查，语义走三态评审。

## 四、三态验收（这个是踩出来的）

第一次端到端跑通了 `pass`/`fail`，但 `explain` 被错判成 `fail`——
它明明只是「结构合格、语义没人看」。所以改成三态：

| verdict | 含义 | 对里程碑 |
|---|---|---|
| `pass` | 机器可判且通过 | 算通过 |
| `fail` | 结构/执行没通过 | 不算通过 |
| `pending` | 结构合格，等评审 | **不算通过，也不算失败** |

评审出口：`POST /api/submissions/review`，写入**新的一条提交记录**（历史不可变），不是改写原记录。

## 五、门禁规则

```python
need = max(requirement.min_level, max(单元内 core 概念的 target_level))
```

单元里所有 core 概念达标，门禁才开。项目在门禁关闭时状态是 `locked`，
`GET /api/projects/{id}` 会直接告诉缺哪个单元、哪个概念差几级。

## 六、用户自己的真实项目是一等公民

```http
POST /api/projects
{"pack_id":"ai-learning-framework","code":"my-rag","title":"我的问答助手",
 "repo_path":"D:/myproj"}
```

`authored_by='user'` 的项目走同一套验收；提交时可以 `artifact_dir` 指向自己的仓库。
重装内容包**不会删除**用户项目（有测试 `test_reinstall_keeps_user_projects`）。

## 七、验收结果如何变成等级

`_link_one()` 把每次提交转成概念证据：

| 提交结果 | 记为什么事件 | 效果 |
|---|---|---|
| `pass` + 里程碑通过 + 非辅助 | `project_pass` | 计入独立通过，可兑现 L5 |
| `pass` + 里程碑通过 + 辅助 | `attempt`(assisted) | 记账，**不推进等级** |
| `fail` | `project_fail` | 计入失败，不推进等级 |
| `pending` | 不记 | 既不算证据也不算失败 |

## 八、示范项目：`fit-diagnosis-report`

门禁：`u-overfitting` 单元到 L3 → 做「模型拟合诊断报告」：

| 里程碑 | 交付物 | kind |
|---|---|---|
| 跑通基线实验 | 实验脚本 | `run` |
| | 结果文件（各项误差） | `data` |
| 给出诊断结论 | 诊断结论 JSON | `data` |
| | 向初学者解释判断依据 | `explain`（4 项 rubric） |

端到端实测（真实 API）：`locked` → 门禁开启 → 3 项 `pass` → `explain` 为 `pending`
→ 项目状态 `in_review` → 评审通过 → `completed`，相关概念到 **L5 迁移**。

## 九、测试

全量 **79 passed**，其中项目层 22 个：

- `test_project.py`（17）：门禁开合、五类交付物、路径越界、三态、评审后完成、辅助不推进、用户项目
- `test_curriculum.py`（+5）：项目装载、非法课程/单元/概念/kind 报错、重装保留用户项目

## 十、必须说清的局限

1. **执行命令的安全边界**：`test` / `run` 会真的执行命令。内容包里的命令是可信输入；
   用户自建项目的命令等同于用户本机执行。**内容包若来源不明，不要装。** 这是设计边界，不是漏洞。
2. **`explain` 目前没有自动评审器**：`review_submission` 已就绪，但还没接 AI 教师按 rubric 评审。
3. **前端未接**：全部只能通过 API 操作。
4. **只有 1 个示范项目**，够证明框架成立，不够当课程用。
