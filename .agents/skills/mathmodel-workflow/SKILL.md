---
name: mathmodel-workflow
description: 以 Capability-First v3 完成整道数学建模赛题的分析、求解、真实实验、独立科学红队、论文、独立 PDF 盲审和机械终检。仅在用户明确要求完整赛题交付时使用；局部分析、调试或改写论文不得隐式启动。
---

# Capability-First v3 数学建模工作流

目标是提升解题、实验和论文质量，而不是让模型维护审核平台。先理解数学结构和可执行路线；脚本自动保存最小可复验证据。

1. 创建运行：

   ```powershell
   python scripts/codex/init_run.py <problem_path> --workflow capability-first-v3 --run-id <run-id>
   ```

   只在用户要求整题、真实实验和完整论文时使用。恢复时只读当前状态和当前阶段产物；`blocked` 必须有失败证据与最小恢复条件，才回到分析、路由或实验。
2. 连续交付：

   | 阶段 | 责任 | 主要产物 |
   | --- | --- | --- |
   | `analysis` | `$mathmodel-solve` 做结构分析、推导和路线比较 | 建模报告 |
   | `capability_route` | `$mathmodel-capability-router` 按题型选择并调用匹配的主动 Skill、工具和本地知识 | 路由与消费收据 |
   | `experiment` | `$mathmodel-experiment` 真实编码、运行和验证 | 结果与实验报告 |
   | `scientific_review` | 新对话用 `$mathmodel-red-team` 从冻结包攻击模型与搜索 | 科学红队报告 |
   | `visualization` | `$mathmodel-visual` 生成真实的模型/求解证据图，并选择模板 | 图表与模板清单 |
   | `paper` | `$mathmodel-paper` 写作和编译 | `paper/final.pdf` |
   | `paper_review` | 另一新对话只读匿名 PDF 盲审 | PDF 盲审报告 |
   | `verify` | `$mathmodel-final-check` 复验提交产物 | 机械 QA |

3. 解题、科学红队和 PDF 盲审必须是三个不同的 Codex 对话。新审查对话只读其冻结包，不访问网络、公开同题答案或历史 run。
4. 主对话优先写题意、变量单位、假设、核心推导、路线比较、probe、结果含义和失败边界。能力路由只填写五项决定：题型、实际能力、独立验证、工具链、本地知识；空间视觉结论仅在相关时补充。哈希、来源、命令和收据由运行时生成。
5. 图表完成后、进入 `paper` 前选择并实例化模板：

   ```powershell
   python scripts/paper/select_template.py runs/<run-id> `
     --language zh --engine auto `
     --reason "比赛和语言匹配，优先 LaTeX。" --materialize
   ```

   `auto` 优先 LaTeX；Typst 仅为用户显式选择或 LaTeX 不可用时的有记录回退。未知赛事不得静默用 `default`。
6. 出现题意、核心模型、硬约束或精确评分错误时，保存最小复现和恢复条件并停止下游；普通实现错误或参数调整在当前路线内修复。正常退出、保住 baseline、空图或模板文本都不等于解题成功。

详细的搜索边界、收据格式和防伪规则只在实际需要时查阅 `docs/CODEX_WORKFLOW.md`，不要把它逐项抄进主对话。
