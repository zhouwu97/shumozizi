# CUMCM 2023-B A/B Arm Prompt

你正在执行 `CUMCM-2023-B` A/B 试点的 `${ARM_ID}` 组。连续工作到该组匿名完整 PDF、代码、
真实实验、结果、成本记录和冻结提交清单完成，或 12 小时墙钟预算耗尽。不要向用户索取建模、
路线选择、调参或审核判断；除非遇到官方输入损坏、权限故障或无法恢复的环境错误，否则自主推进。

## 冻结身份

- Arm：`${ARM_ID}`；
- Git 基线：`${GIT_REF}`；
- 运行目录：`runs/CUMCM-2023-B-${ARM_ID}`；
- 启动顺序：B 后 A 中的 `${LAUNCH_POSITION}`；
- 匿名论文代码：`${PAPER_CODE}`，正文和提交包不得出现 A/B 或流程版本；
- 总墙钟预算：12 小时；
- 基础模型、工具权限、硬件、初始人工信息和 Prompt 总预算与另一组相同；
- 本任务只有这一份初始 Prompt，运行期不接收人工建模建议。

## 唯一允许输入

只读取：

- `E:/AI/shumo/CUMCM-2023-B-official/problem/B题.pdf`；
- `E:/AI/shumo/CUMCM-2023-B-official/problem/附件.xlsx`；
- `E:/AI/shumo/CUMCM-2023-B-official/problem/result1.xlsx`；
- `E:/AI/shumo/CUMCM-2023-B-official/problem/result2.xlsx`；
- `E:/AI/shumo/CUMCM-2023-B-official/problem/format2023.doc`；
- `E:/AI/shumo/CUMCM-2023-B-official/pilot-control/OFFICIAL_INPUT_MANIFEST.json`；
- 当前 Git 基线中的运行时、Skills、测试和基础工具文档。

开始前复验官方输入 manifest 和全部 SHA-256。禁止网络检索，禁止读取官方讲评、同题论文、
同题博客、同题代码、已有答案、仓内 `knowledge/` 案例、另一组 worktree 或任何 cross-arm 产物。
不得读取 `BLIND_MAPPING.json`；匿名代码只使用本 Prompt 给出的 `${PAPER_CODE}`。

## AI 自主路线选择

本次人类选题决定已授权 AI 自主选路，路线阶段没有交互式人工参与。你必须：

1. 从官方题面独立重构全部 required outputs；
2. 生成 2–3 条数学本质不同且覆盖全部问题的候选路线；
3. 按直接回答能力、正控制可设计性、可证伪性、实现成本、失败风险和 12 小时内论文价值比较；
4. 自主选择期望价值最高的路线，并冻结候选、评分、反例、fallback 和选择理由；
5. 写 `pilot/AI_ROUTE_SELECTION.json`，明确 `selection_actor=AI`、用户只批准自主选择机制而未批准
   具体路线；不得生成或伪造 human route approval receipt；
6. 若常规 StateService 因人工路线门不能推进，使用明确标记为 pilot-only 的自主路线锁继续实际
   建模、实验和论文，但不得把该运行声明为常规工作流 `COMPLETE`。

路线失败时由 AI 自主执行已冻结 fallback。任何题意、核心目标、硬约束、模型族或数据划分实质
改变都要记录漂移原因和新选择证据，但不等待人工建模意见。

## 组别规则

`${ARM_RULES}`

## 预算与产物

建议预算：题意与路线 2 小时，最小模型和实验 5 小时，论文组装 3 小时，R3/R4/R5 与修订
1 小时，异常收敛 1 小时。可在总预算内自主调配；必须记录每个阶段、首次风险信号、路线停止、
fallback、结果冻结和 PDF 完成的墙钟时间。

所有数值、表格和图必须来自真实执行。至少完成题面要求的输出文件、可复现实验、正控制、
baseline/primary 比较、约束检查、稳健性或敏感性分析、完整匿名 PDF 和提交清单。不得编造指标、
引用、盲评分数或缺失附件。

需要 R1-R5 独立上下文时，本 Prompt 明确授权你自行创建新的 Codex 顶层审核任务；审核任务只能
读取本组冻结 manifest，不得读取另一组或历史审核结论。主任务核验报告并定向修复。最终组内
提交冻结后停止，不解盲、不读取另一组、不执行跨组比较。
