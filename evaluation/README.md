# Competition-First 评测

该目录评测流程效果，不为运行时协议背书。所有 A/B 比较固定模型版本、Token、总时间、算力、资料、模板和人工干预次数；未完成的对照不得写成竞争力提升。

1. `tasks/smoke_manifest.json` 定义优化、预测/统计、机理/几何三题烟雾。它只确认主链、PDF、审查和 QA 可运行。
2. `benchmark_manifest.json` 是 12--16 题 held-out 清单的占位契约。填充后必须把每题材料、类别、预算和对照版本固定下来。
3. `pairwise_paper_review.py` 只随机化并去来源化 A/B PDF 顺序；实际 reviewer 仍须不知道来源。
4. `error_injection/manifest.json` 覆盖目标语义、时间泄漏、不可行、proxy/exact 反转、连续量采样伪造、下游传播、旧图和 PDF 数字冲突。
5. `process_metrics.py` 汇总运行时间、协议维护、审核、无价值实验、路线切换和论文长度。它不计算胜率或替代盲评。

初始通过条件应同时报告 pairwise 胜率、实验时间占比、协议维护时间、审核任务数、致命错误发现率和可复述题目特定贡献的论文比例。没有真实结果不得宣称达到阈值。
