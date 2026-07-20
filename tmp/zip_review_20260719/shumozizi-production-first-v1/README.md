# shumozizi

面向数学建模比赛的**生产优先工作流**。

本仓库不是资格认证平台，也不以 Gate、Seal、Manifest 或审查报告数量衡量能力。它服务于：

```text
题意确认
→ 建模方案
→ 编码与实验
→ 论文并行写作
→ 建模/复现/逻辑分层审查
→ 格式与提交核包
```

## 为什么新建这条主线

对 `zhouwu97/shumoziyong` 的实际检查表明，Contest v2 已经具备 Result、Verification、Ledger、Typst 数值绑定和提交打包等可靠工程部件，但其 CLI 只创建 TODO 骨架并负责验证，没有真正执行题意分析、模型路线选择、实验设计和完整论文写作。

继续加强 Paper Admission、学习资产治理和独立 Reviewer，只会让“不合格论文被更准确地拒绝”，不能自动把技术报告变成参赛论文。

因此本仓库采用以下边界：

- **比赛生产**放在这里；
- `shumoziyong` 保留为审计、复现、训练和长期能力验证平台；
- 只复用轻量可信部件，不迁移旧 Gate 状态机；
- 普通比赛默认不启用 `formal_audit`。

## 入口

1. 阅读 `docs/AUDIT_REPORT.md`
2. 按 `docs/WORKFLOW_V1.md` 执行
3. Agent 遵守 `AGENTS.md`
4. 论文从 `templates/paper/` 建立
5. 三类审查分别使用 `templates/review/`

## 四个硬检查点

```text
G0 题意与路线确认
G1 模型可执行且无根本矛盾
G2 关键结论有可复现证据
G3 最终论文与提交包合规
```

其余检查默认给出修订建议，不阻断持续生产。
