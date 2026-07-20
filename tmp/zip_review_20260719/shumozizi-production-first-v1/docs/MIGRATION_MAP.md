# 从 `shumoziyong` 迁移到生产主链的边界

## 直接复用

| 旧部件 | 新用途 |
|---|---|
| `result_ledger.py` | 当前结果快照与关键数值统一来源 |
| `typst_values.py` | 论文数字自动绑定 |
| `verification.py` | 每问独立检查器框架 |
| `verify_package.py` 的排除规则 | 支撑材料打包 |
| Result 变化使 Verification stale | 防止旧验证继续有效 |
| 问级目录结构 | 模型、代码、结果、图表、正文纵向闭环 |

## 重写

| 旧部件 | 重写原因 |
|---|---|
| `cli.py init` | 当前只生成 TODO，需生成完整论文工程和工作目录 |
| `paper/main.typ` | 不满足 2026 页边距、摘要分页、附录和 AI 披露要求 |
| `docs/workflows/03_新题执行流.md` | 改为先建模审查、再复现、再逻辑、最后格式 |
| Reviewer 流程 | 普通比赛只做一次完整终审，修订按影响范围复核 |
| Paper Admission | 11 项手填矩阵改为自动 claim-evidence map |

## 仅保留在 `formal_audit`

- Gate 0–5
- Qualification/Profile
- Capability Evidence
- Manifest/Seal
- Formal Result
- 输入冻结与长期证据
- 学习规则晋级治理
- 每轮全新 Reviewer 对话
- 严格 PDF/学习上下文摘要绑定
- 多轮独立复审

## 不迁移到普通比赛

- 资格通过/不通过
- `production_ready` 状态
- 用旧题回放次数推断竞赛能力
- 逐问 11 项人工准入矩阵
- 强制每题选择学习规则
- AI 痕迹概率或“AI率”
- 为保证审计而生成的大量中间 JSON

## 首批实现任务

### P0

1. 新 CLI：`init / model-review / run / reproduce / paper / review / package`
2. 2026 合规 Typst 模板
3. 建模、实验、论文三类审查模板
4. `claim_evidence_map` 自动生成
5. 变更影响判断
6. PDF/支撑包大小检查
7. 匿名词扫描
8. AI 使用详情模板和核包检查

### P1

1. 题面与附件解析器
2. 子问题依赖图
3. 图表—结论映射
4. 论文完整性静态检查
5. 第二道陌生题生产验收

### P2

1. 模型路线建议库
2. 题型专属实验最低证据
3. 自动差异复核
4. 赛后 `formal_audit` 导出到 `shumoziyong`

## 验收方式

不能只跑单元测试。至少完成：

1. 一道无现成专用代码的陌生题，从题面到完整 PDF；
2. 一道不同题型的第二题；
3. 记录题意确认次数、建模返工次数、首次完整稿时间、最终页数、独立终审问题数；
4. 人工确认论文能脱离代码独立理解；
5. 验证普通比赛过程中没有启动资格、Seal 或长期能力状态。
