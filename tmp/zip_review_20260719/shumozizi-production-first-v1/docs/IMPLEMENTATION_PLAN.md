# 实施计划

## 阶段 1：先把论文模板和流程改对

- 落地 `templates/paper/main.typ`
- 增加摘要专用页和强制分页
- 页边距统一为至少 2.5 cm
- 增加参考文献、AI 使用声明、支撑材料列表和源程序附录
- 建立三类审查模板
- 移除普通比赛的 11 项 Paper Admission 手填要求

## 阶段 2：建立轻量作者编排

建议命令：

```text
contest init
contest brief
contest model-review
contest run
contest reproduce
contest paper
contest final-review
contest package
```

各命令只负责一个清楚阶段，不维护资格状态。

## 阶段 3：复用可信数值链

从 `shumoziyong` 选择性移植：

```text
result.json
→ verification.json
→ result_ledger.json
→ generated/results.typ
→ paper
```

不移植 Gate、Profile、Capability、Seal。

## 阶段 4：真实生产验收

先用一道陌生旧题，不使用现成题目专用代码：

- 人工确认题意与路线；
- 完成主模型和廉价基线；
- 建模审查；
- 编码与复现审查；
- 同步写完整论文；
- 一次独立终审；
- 格式核包。

若最终仍是短技术报告，不继续加审查字段，直接修作者编排和论文模板。
