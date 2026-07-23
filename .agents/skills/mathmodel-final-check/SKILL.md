---
name: mathmodel-final-check
description: 对已通过独立 PDF 盲审的 Capability-First v3 论文执行机械 QA、追溯复验和 PDF 内容覆盖报告；仅在 verify 阶段、完整 PDF 即将提交时使用。
---

# 最终机械检查

只检查确定性提交错误、结果追溯与 PDF 内容覆盖。机械通过不代表模型正确、搜索充分或具有竞赛竞争力；这些判断必须已经由新的 `$mathmodel-red-team` 科学审查完成，不能在本 Skill 中以关键词、哈希或同源 oracle 伪造。

## 机械 QA

运行：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

该命令输出 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 和 `reports/VERIFY_REPORT.md`。它阻断 PDF 缺失/损坏、空白页、明显裁切或文字重叠、占位符、失效结果引用、内容蓝图中有生产证据却缺少逐问 `@result`、数值证据却缺少 `@metric`、current 结果哈希变化、指标来源变化、科研模板图的源结果替代/输入输出哈希漂移及关键数值不一致等确定性错误。它还复验能力路由要求的图表叙事合同已完成、图表输出未漂移、完整写作模板与比赛/引擎仍匹配。图表/表格编号只从图注和表题推断，目前作为 warning，避免正文正常引用造成误报。匿名投稿时追加 `--anonymous`，并可用 `--anonymous-term` 传入队名、学校等禁止词。必要时可单独使用 `tools/qa/figqa.py`、`pdf_qa.py` 或 `make_contact_sheet.py` 定位问题。

终检和提交事实只接受 production scope、`status=current`、`execution_valid=true`、同合同组 registry accepted/incumbent 且完整独立 evidence chain 的结果。该链必须包含：generator 的原始 candidate pool/trace，exact scorer 独立重算硬约束和 exact objective 的产物，以及 search auditor 从原始输入重算覆盖、校准、挑战独立性和选择影响的产物；三者都要匹配冻结合同的 adapter id/version、受控源路径和命令、输入输出 hash。通用层只验证这些 provenance、路径边界和漂移，不把它们误报为通用数学证明。对多实体题还核对共同/实体/交互变量的原生联合覆盖与并集 marginal-gain 语义；均值、首元素或低维投影不能作为联合覆盖。对挑战核对冻结 incumbent、允许但明确标记的 baseline/warm start、独立新候选、独立覆盖、实际新区域及独立 exact 重算。对下游题核对合同声明的前序 production accepted/current 未降级。

生成器自报的 `feasibility`、`exact_recomputed`、`search_adequacy`、`problem_effectiveness` 和 legacy 质量布尔字段都只是 diagnostic，不能降低上述证据要求。独立且可比但不改善的挑战应保留 incumbent 并可作为稳定性证据；充分但较差的挑战是无信息或较弱搜索族，绝不覆盖 incumbent；只有 scorer 或模型语义错误才会推翻 incumbent。`exploration`、legacy `diagnostic/unverified`、候选、拒绝、未评估、运行 `blocked` 或存在未解决 P0/P1 的结果必须拒绝；不能因文件哈希正确、恢复 baseline 或挑战正常退出而放行。

若运行目录登记了 `paper/paper_references.json` 或 `paper/contribution_ledger.json`，机械 QA 还必须分别重放论文卡收据和贡献账本：前者检查冻结 production 结果、受控知识索引与卡哈希，后者检查当前 production 证据、限制，以及数学创新所需的机制→预测→对照→单组件消融链。两者任一漂移或失效都阻断终检；未使用这些可选接口的历史运行不因缺少文件而失败。

## PDF 内容覆盖报告

在 `reports/VERIFY_REPORT.md` 中单列“PDF 内容覆盖”段落，报告而不是伪造自动科学结论。至少逐项记录 Q1-Q5 是否有可定位的直接答案，以及是否包含题目要求/采用解释、模型或核心公式、实际求解、当前运行结果、验证和限制等必要内容块。关键词和页数只用于定位问题；它们不能判断公式是否正确、模型是否深入或结果是否有竞争力。

同时按页和章节报告页数、公式、图、表和引用的可疑密度，例如异常空洞、堆砌、正文没有支撑结果或结果没有解释。它们是供整体审查定位的 warning，不是通用美学或竞赛质量评分：不同题型的合理密度不同，页数、公式数、图表数或引用数单独异常均不得成为 blocker。只有与直接答案缺失、不可读、错误引用、无证据主张或提交要求冲突相结合时，才按其实际后果升级问题等级。

贡献账本在这里仅做追溯复验：每项所谓结构、模型、算法、实证或表达贡献必须能回指本次 production 运行证据与限制。通用 Skill、质量协议、已有算法的直接调用和普通图表不能被写为数学创新；仅有工程实现或方法组合时，论文必须如实表述。该检查只验证证据存在与未漂移，不裁定创新的数学价值。

最终 PDF、提交材料或任何可见结论被修改后，之前的 PDF 盲审自动失效。回到 `paper_review`，重新建立盲审包；不要以重新运行机械 QA 代替。
