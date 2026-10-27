# 学习框架（Learning Framework）v1

学习框架是 AnyLearn 在「题库 + 掌握度 + 复习」之外新增的一层：**教学过程本身的结构化**。
它回答的不是「你答对了多少题」，而是 **「你现在该学什么、卡在哪、凭什么说你会了」**。

## 一、解决了什么

原有 AnyLearn 是「做题驱动」：知识树 + 题目 + 作答 → 掌握度 → 复习。
缺的是中间的**教学环节**：先诊断、再追问、再讲解、再让学生自己讲一遍、再独立验收。

本框架补齐了这一段，并且明确规定了一条底线：

> **能力等级只能由证据推导，模型不能直接给分。**

## 二、数据模型（迁移 `003_learning_framework.sql`）

```
概念 concept ──先修──> 概念
   │
课程 course ─ 单元 unit ─ 步骤 step ──> 概念
                │
                └── 单元目标：每个概念要练到 L?
```

| 表 | 作用 |
|---|---|
| `concepts` | 可教可测的最小单位，附 `misconceptions`（预设误解，供苏格拉底追问用） |
| `concept_prerequisites` | 先修关系；`strength=1.0` 硬先修 |
| `courses` / `course_units` / `unit_concepts` | 课程 → 单元 → 单元要覆盖的概念及目标等级 |
| `unit_steps` | 教学步骤，`kind` ∈ diagnose / explain / socratic / feynman / practice / verify / review |
| `learning_events` | **不可变事实源**（与 `attempts` 并列），教学过程发生的一切 |
| `concept_ability` | 等级投影，可由事件**重放重建** |
| `unit_progress` | 单元进度投影 |

**为什么不复用 `attempts`**：`attempts` 是「答题」事件；教学过程还包括「看了讲解」「用了提示」「讲了一遍」「通过验收」。语义不同，混在一起会让事实源变模糊。

## 三、等级规则（L1–L5）

| 等级 | 含义 | 达成条件（全部来自事件） |
|---|---|---|
| L0 | 未接触 | 无事件 |
| L1 识别 | 见过、能分辨 | ≥1 次**独立**通过 |
| L2 解释 | 能用自己的话说清 | L1 + 1 次非辅助 `self_explain` |
| L3 应用 | 有限提示下完成任务 | L2 + ≥2 次独立通过 |
| L4 诊断 | 能定位问题、比较方案 | L3 + ≥3 次独立通过 + **0 次误解命中** |
| L5 迁移 | 陌生场景仍成立 | L4 + 非辅助 `verify_pass` + ≥4 次独立通过 |

**关键规则**：`hint_level > 0` 的事件记为 `assisted=1`，只计辅助通过，**不推进等级**。
这条规则在 `test_assisted_passes_do_not_advance` 里被钉死。

## 四、卡点诊断（`diagnose_blocker`）

不返回百分比，返回**可解释的依据与下一步动作**，按优先级：

| 代码 | 触发条件 | 下一步 |
|---|---|---|
| `misconception` | 命中过预设误解 | 针对误解做一次苏格拉底追问 |
| `prerequisite_gap` | 先修等级 < `required_level` | 先补先修概念 |
| `hint_dependency` | 只有辅助通过、无独立通过 | 撤掉提示重做 |
| `no_evidence` | 无记录 | 从诊断题开始 |

`required_level` **显式参数化**，缺省取自本概念所在单元的核心目标等级。
这条是有意设计的：最初版本把「先修达标线」硬编码为 L2，测试立刻暴露了问题——一个目标 L3 的概念，配一个定义成 `target_level=1` 的先修，规则就自相矛盾了。现在规则要么来自参数，要么来自单元声明，不藏在代码里。

## 五、内容包协议新增：`data/curriculum.json`

```json
{
  "concepts": [
    {"code": "overfitting", "name": "过拟合", "module_id": "basics",
     "summary": "一句话定义", "misconceptions": ["参数越多一定越好"],
     "prerequisites": ["generalization"]}
  ],
  "courses": [{
    "code": "ml-foundations", "title": "机器学习入门", "goal": "学完能独立判断过拟合",
    "units": [{
      "code": "u-overfitting", "title": "第一单元", "objective": "能独立判断并解释",
      "concepts": [{"code": "overfitting", "role": "core", "target_level": 3}],
      "steps": [
        {"kind": "diagnose", "concept": "overfitting", "title": "...",
         "content_ref": "E:/AI教学资料/...pdf#p44", "config": {}}
      ]
    }]
  }]
}
```

- **可选文件**：没有 `curriculum.json` 的内容包照常工作，只是不提供学习单元（`test_pack_without_curriculum_still_works`）。
- **`content_ref`**：指向教材的具体页码，是「讲解可点开出处」的落点。
- **校验**：概念 code 唯一；先修必须存在且不能自指；步骤 `kind` 必须在枚举内；`target_level` 1..5。
- **升级安全**：重装内容包会刷新概念/课程/单元，但**不清 `learning_events`**（`test_reinstall_keeps_learning_events`）。

## 六、REST 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/packs/{id}/courses` | 课程与单元 + 进度 |
| GET | `/api/courses/{course_id}/next` | 当前该学的单元 |
| GET | `/api/units/{unit_id}` | 步骤清单 + 概念等级 + 当前卡点 |
| POST | `/api/learn/steps/done` | 标记步骤完成并推进 |
| POST | `/api/learn/events` | 记录学习证据（**不接受 level 字段**） |
| GET | `/api/concepts/{id}/diagnose` | 卡点诊断 |

`/api/learn/events` 刻意不接收 `level`：等级是投影，不是输入。

## 七、示范内容包：`content-packs/ai-learning-framework`

只含教学结构，**不含任何题目**（题库按计划暂缓）。第一单元「过拟合与泛化」走完整闭环：

```
1 diagnose  训练 99% / 测试 65%，学得好吗？          → ISLR p44
2 socratic  追问：如果只是记住了训练样本会怎样？      → ISLR p47
3 explain   训练误差 vs 测试误差（U 形曲线）          → ISLR p41
4 feynman   讲给初学者听，举例子并说出局限            → 评分四项
5 practice  改模型复杂度，观察误差曲线                → ISLR p43
6 verify    换陌生数据独立判断，不许提示              → 无出处
```

页码是通过在 PDF 内检索 `flexibility / test error / training error` 定位的，不是估的。

## 八、测试与验证

- 全量：**57 passed**（原有 36 个零回归）
- 新增 21 个：`test_lesson.py`(12) / `test_curriculum.py`(7) / `test_learning_flow.py`(2)
- API 冒烟：装包 → 列课程 → 取 next → 取单元 → 标记步骤 → 记事件 → 诊断，全部 200

## 九、下一步（未做）

1. **前端未接**：`backend/app/static/` 里的页面还没有学习单元的界面。
2. **AI 教师未接**：socratic / feynman 步骤目前只是结构 + 配置，还没有调用 `teacher.py` 生成追问与按 rubric 评分。
3. **题库挂载**：按你的要求暂缓，等知识树重建后再做。
4. **verified 内容**：目前只有 1 个单元，需要扩展到成体系的课程。
