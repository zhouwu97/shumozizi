# 科研绘图模板人工视觉审计

本审计使用 QA 数据，**不进入论文证据链**。全部模板实际生成 PNG、PDF、SVG，并在 15.8 cm、300 dpi 的论文宽度下检查；同时查看彩色、灰度以及 MathModel 参考预览与生产渲染器的并排图。安装目录的 11 张预览逐字节一致，11 个模板脚本在统一换行后与仓内版本一致。

等级含义：`preview_grade` 表示高级结构已由真实数据合同驱动并通过本轮人工晋级，不表示逐像素复制；`safe_adapted` 表示证据语义可靠但视觉丰富度低于参考；`needs_visual_refinement` 表示只可留在深化队列，不能自动推荐为高级成品。逐模板差距和灰度结论见 `audit.json`。

## 审计结论

- `preview_grade`：paired-raincloud、nature-chord-diagram，以及仓内原生的 feasible-region-active-constraints、interval-event-timeline、uncertainty-fan-threshold、multi-panel-evidence-chain。
- `safe_adapted`：cv-roc-ci、correlation-pairgrid、rf-tpe-surface、taylor-diagram。
- `needs_visual_refinement`：prediction-marginal-grid、multiclass-shap-combo、grouped-corr-split-violin、grouped-circular-heatmap、urban-park-cooling-combo。

RF/TPE 图中的黑点是实际 trials，曲面和等值区只表示离散试验点间的三角插值，不可写成真实连续目标函数。Taylor 图要求所有模型共享同一参考标准差。SHAP、关系和弦、环形周期等模板仅在相应结构由真实计算或真实数据支持时使用。

`production/` 与 `paper-width-15.8cm/` 是可再生中间产物，不作为最终改动保留；仅保留三张代表性 contact sheet 与本报告。
