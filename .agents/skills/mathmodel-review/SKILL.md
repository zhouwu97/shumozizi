---
name: mathmodel-review
description: 对数学建模论文执行一次机械检查、一次评委视角自审、一次定向修复和一次快速复检。用于已完成草稿的提交前验证，结束时必须生成最终审核备忘并停在人工终审点。
---

# 有界论文自审

不重新建模，不启动三席评审，不进行无限润色或多轮返工。

## 前置条件

1. 只在 `state.json` 为 `PAPER_DRAFTED` 时执行。
2. 完整读取 `skills/6verity/SKILL.md`，只复用其中的机械检查和小范围修复规则。
3. 读取路线锁、数学规格、结果注册表、论文源文件和最终 PDF。

## 固定预算

1. 一次机械检查：编译、图片路径、占位符、引用、提交格式、关键数值一致性和逐页 PDF 检查。
2. 一次单一 Critic：只审题意、模型匹配、创新证据、结果解释和最可能扣分的缺陷。
3. 一次定向修复：只改上述明确问题，禁止顺手改模型或新增未经批准的实验。
4. 一次快速复检：确认修复没有破坏编译、数值、图表和格式。

机械错误可以直接小修；任何路线漂移必须写 `review/ROUTE_DRIFT_MEMO.md` 并返回人工路线确认。

## 输出和暂停

写入：

- `review/MECHANICAL_CHECK.md`
- `review/CRITIC_REPORT.md`
- `review/REPAIR_LOG.md`
- `review/FINAL_REVIEW_MEMO.md`

把 `state.json` 更新为：

- `status`: `WAITING_HUMAN_FINAL`
- `completed_stages`: 加入 `self_review`
- `active_stage`: `human_final_review`
- `paper_ready`: `true`

执行状态校验，向用户报告最终 PDF 路径、关键风险和建议小改，然后停止。只有用户明确批准后，
完整工作流才能把状态改为 `COMPLETE`。
