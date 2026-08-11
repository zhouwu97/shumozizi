# 结构图 spec 契约（SECOND STEP 结构图 renderer）

结构图走 **structure spec → TikZ renderer**，不是自然语言 prompt → TikZ。
AI 决定语义（中心对象、关系、强调层级、公式），程序决定几何（坐标、间距、字号、线型）。

## 边界（不可协商）

- **TikZ 只做解释性结构图，不进 evidence layer**。
  `argument_role` 为 `decisive_evidence` 时 renderer 拒绝（证据图必须走数据 renderer）。
  允许角色：`model_understanding / mechanism / boundary / insight / tradeoff / stability`。
- 结构图不承担数值证据；它的价值是让"共享模型、问题继承、机制判定"这些论证结构可见。
- draw.io 只用于人工草图/reference；正式结构图用 TikZ。

## 重复控制（不可协商）

- **结构图不是"模板可用"就生成，而是只有当它减少正文解释成本时才进入论文。**
- 优先级：**共享模型总图 > 关键机制图 > 问题递进图**。
- **全文通常 1--2 张结构解释图已经足够**，除非不同机制确实不能由同一张图承担。
- 如果正文已有一张总体模型图，不得因为 Q1--Q4 都能套模板就连续生成 3--4 张类似结构图。
- 判定问题：这张图删除后，正文解释共享模型/继承/机制的成本是否明显上升？
  答案是否定就不画。这防止结构图把论文推回"报告/信息图集合"。

## Spec JSON

```json
{
  "template": "shared_model_map",      // 三选一
  "title": "共享模型路线图",
  "argument_role": "model_understanding",
  "nodes": [
    {"id": "geom", "label": "几何接触网络", "role": "input"},
    {"id": "core", "label": "共享状态", "role": "center",
     "math": "S(t)=\\{x_e(t),q_e(t),V_e(t)\\}_{e\\in E}"},
    {"id": "q1", "label": "问题一：判定", "role": "output"},
    {"id": "constraint", "label": "导通阈值 1.8nm", "role": "state"}
  ],
  "edges": [
    {"from": "geom", "to": "core", "kind": "feed"},
    {"from": "core", "to": "q1", "kind": "inherit"},
    {"from": "constraint", "to": "core", "kind": "condition"},
    {"from": "q2", "to": "core", "kind": "feedback", "label": "回填"}
  ],
  "emphasis": ["core"]
}
```

## 模板与语义角色

- **shared_model_map**：中央共享模型（`role=center`，可 `math` 公式无边框）、
  左输入（`input`）、右问题输出（`output`）、上状态/约束（`state`/`top`/`bottom`）。
- **problem_progression**：水平递进 Q1→Q2→…，边 `label` 标注"上一问如何进入下一问"，
  `kind=inherit` 虚线继承，`feedback` 回环。
- **mechanism_decision**：`input` → `state`（状态更新）→ `condition`（条件/阈值）→ `output`，
  可 `feedback` 回环。

边 `kind`：`feed`（实线）、`inherit`（虚线继承）、`condition`（灰实线条件）、`feedback`（弯回环）。

## AI 决定 / 程序决定

| AI 决定 | 程序决定 |
|---|---|
| 谁是中心、谁是输入/输出/状态 | 坐标、间距、节点形状 |
| 哪条边是继承/反馈/条件 | 线型、箭头、弯曲 |
| 哪个节点强调 | 填充/边框强调 |
| 哪些公式直接出现（`math` 字段） | 公式排版、字号 |
