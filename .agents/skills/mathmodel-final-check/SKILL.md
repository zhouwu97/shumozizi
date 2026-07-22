---
name: mathmodel-final-check
description: 对 Capability-First v3 论文执行一次机械 QA 和一次整体科学审查；仅在完整 PDF 即将提交时使用，重大修复后最多做一次定向复查。
---

# 最终机械检查与整体审查

先检查确定性提交错误，再用完整产物做一次整体审查。机械通过不代表模型优秀，审查意见也不替代真实执行。

## 机械 QA

运行：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

该命令输出 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 和 `reports/VERIFY_REPORT.md`。它阻断 PDF 缺失/损坏、空白页、明显裁切或文字重叠、占位符、失效结果引用、current 结果哈希变化、指标来源变化、科研模板图的源结果替代/输入输出哈希漂移及关键数值不一致等确定性错误。图表/表格编号只从图注和表题推断，目前作为 warning，避免正文正常引用造成误报。匿名投稿时追加 `--anonymous`，并可用 `--anonymous-term` 传入队名、学校等禁止词。必要时可单独使用 `tools/qa/figqa.py`、`pdf_qa.py` 或 `make_contact_sheet.py` 定位问题。

终检和提交事实只接受 production scope、`status=current`、`execution_valid=true`、同合同组 registry accepted/incumbent 且完整独立 evidence chain 的结果。该链必须包含：generator 的原始 candidate pool/trace，exact scorer 独立重算硬约束和 exact objective 的产物，以及 search auditor 从原始输入重算覆盖、校准、挑战独立性和选择影响的产物；三者都要匹配冻结合同的 adapter id/version、受控源路径和命令、输入输出 hash。通用层只验证这些 provenance、路径边界和漂移，不把它们误报为通用数学证明。对多实体题还核对共同/实体/交互变量的原生联合覆盖与并集 marginal-gain 语义；均值、首元素或低维投影不能作为联合覆盖。对挑战核对冻结 incumbent、允许但明确标记的 baseline/warm start、独立新候选、独立覆盖、实际新区域及独立 exact 重算。对下游题核对合同声明的前序 production accepted/current 未降级。

生成器自报的 `feasibility`、`exact_recomputed`、`search_adequacy`、`problem_effectiveness` 和 legacy 质量布尔字段都只是 diagnostic，不能降低上述证据要求。独立且可比但不改善的挑战应保留 incumbent 并可作为稳定性证据；充分但较差的挑战是无信息或较弱搜索族，绝不覆盖 incumbent；只有 scorer 或模型语义错误才会推翻 incumbent。`exploration`、legacy `diagnostic/unverified`、候选、拒绝、未评估、运行 `blocked` 或存在未解决 P0/P1 的结果必须拒绝；不能因文件哈希正确、恢复 baseline 或挑战正常退出而放行。

若运行目录登记了 `paper/paper_references.json` 或 `paper/contribution_ledger.json`，机械 QA 还必须分别重放论文卡收据和贡献账本：前者检查冻结 production 结果、受控知识索引与卡哈希，后者检查当前 production 证据、限制，以及数学创新所需的机制→预测→对照→单组件消融链。两者任一漂移或失效都阻断终检；未使用这些可选接口的历史运行不因缺少文件而失败。

## PDF 内容异常报告

在 `qa/FINAL_REVIEW.md` 中单列“PDF 内容异常”段落，报告而不是伪造自动科学结论。至少逐项记录 Q1-Q5 是否有可定位的直接答案，以及是否包含题目要求/采用解释、模型或核心公式、实际求解、当前运行结果、验证和限制等必要内容块。直接答案缺失、关键内容块缺失或结果与答案不一致，应按实际影响列为 P0/P1/P2 并说明页码或章节；不能只依赖关键词匹配。

同时按页和章节报告页数、公式、图、表和引用的可疑密度，例如异常空洞、堆砌、正文没有支撑结果或结果没有解释。它们是供整体审查定位的 warning，不是通用美学或竞赛质量评分：不同题型的合理密度不同，页数、公式数、图表数或引用数单独异常均不得成为 blocker。只有与直接答案缺失、不可读、错误引用、无证据主张或提交要求冲突相结合时，才按其实际后果升级问题等级。

贡献账本也在此复核：每项所谓结构、模型、算法、实证或表达贡献必须能回指本次 production 运行证据与限制。通用 Skill、质量协议、已有算法的直接调用和普通图表不能被写为数学创新；仅有工程实现或方法组合时，应检查论文是否如实表述。任何题目数学创新还须呈现机制差异、可检验预测、明确比较口径的改善，以及独立角色的单组件消融；对照/消融可来自角色独立的 current 结果，或同一 primary exact scorer 的两个受控附属产物。缺失任一证据只能降级，不能用流程改进补足。

## 一次整体科学审查

读完整论文、代码、`results/index.json`、机械报告和联系表，写入 `qa/FINAL_REVIEW.md`。只检查：

- 是否覆盖全部必答问题并逐问直接回答；
- 模型是否对准题目目标；
- 关键结果是否有信息量，baseline 是否公平，正控制是否通过；
- 是否存在不可辨识、泄漏、不可行或不合理外推；
- 主张是否夸大，失败路线是否被包装为贡献；
- 最限制奖项竞争力的一项问题。

按 P0（基本无效/未回答）、P1（显著影响提交）、P2（局部缺口）、P3（可选优化）分级。只有 P0/P1 才触发一次定向修复；格式小改或 P2/P3 不得再开完整审查。核心模型、数据或结论发生重大变化时，允许一次定向复查并说明范围。
