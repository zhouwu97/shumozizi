---
name: mathmodel-visual
description: 为 Capability-First v3 已通过科学红队的数学建模运行规划、生成和登记模型证据图、搜索诊断图与论文图表叙事。仅在 visualization 阶段使用；适用于几何、优化、机理、网络、预测和评价题，不用演示数据或装饰图替代真实证据。
---

# 建模可视化叙事

图表是模型和求解过程的证据，不是论文篇幅填充。此阶段不重跑生产求解、不修改结果事实，也不绕过已经通过的科学红队。

1. 读取 `state/capability-route.json`、科学红队结论、当前 `results/index.json`、`ANALYSIS_MODELING_REPORT.md`、`RESULTS_REPORT.md` 与 `DECISIONS.md`。先确定每张图要回答的论证问题、数据来源、局限和论文位置。
2. 根据题型形成 Figure Contract。系统会要求以下实质角色，不能用若干时间条形图替代：

| 题型 | 必需视觉证据 |
| --- | --- |
| 几何/运动 | 空间场景图、关键有限边界图 |
| 优化 | 收敛过程、搜索诊断（景观切片或 proxy-exact 校准） |
| 机理/动力学 | 状态轨迹、相图或场分布 |
| 网络 | 拓扑、路径或流量图 |
| 预测/统计 | 拟合、残差或不确定性图 |
| 评价/排序 | 权重敏感性或排名稳定性图 |

多问赛题还需一张方法路线图。若图确实不适用，必须在路由阶段避免声明相应题型；必需角色不能事后豁免。
3. 工具由图的证据任务决定：数据图优先读 `skills/3coding-visual/SKILL.md`；技术路线或变量关系图读 `skills/4drawio/SKILL.md`；空间运动和独立图形核验按路由调用 `$mathmodel-matlab`；统计模板仅在真实结果数据接口匹配时使用 `skills/mathmodel-figure-templates/`。模板演示数据绝不进入论文。
4. 将生成脚本保存至 `code/figures/` 或 `code/matlab/`，输出写入 `figures/`。每张完成图至少导出一张可读取、分辨率足够的 PNG；需要矢量稿时可额外导出 PDF 或 SVG。空间图应明确坐标、单位、对象、轨迹、关键事件与可见边界；优化图必须说明评价口径，不能把同源 proxy 当 exact。
5. 登记计划与已完成输出。`complete` 图可在 `outputs` 中只写路径，脚本会冻结 SHA-256：

   ```powershell
   python scripts/figures/record_visualization.py runs/<run-id> `
     --input code/visualization-plan.json
   ```

   `production_result` 图只能引用已被独立证据链放行的 `result_ids`。模型示意、搜索诊断和路线图必须明确为相应证据范围，不能混写为数值事实。
6. 所有必需 Figure Contract 完成后才可进入 `paper`。正文须解释图怎样支持模型、选择或限制，而不只在图注重复标题。
