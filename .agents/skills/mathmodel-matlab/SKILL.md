---
name: mathmodel-matlab
description: 在 Competition-First v3.2 中使用真实 MATLAB/Octave 完成建模、优化、仿真、独立复算和科学绘图；不把工具品牌当作独立性或正确性证明。
---

# MATLAB / Octave 建模与独立实现能力

MATLAB/Octave 不是每题必选。出现矩阵计算、连续/整数/多目标优化、ODE/PDE、控制仿真、信号与图像、曲面拟合、三维场或网络流时主动比较；只有它能利用题目结构、形成不同算法族/判定实现、提供明显更强仿真绘图，或承担独立 oracle/challenger 时启用。先读 [modeling-recipes.md](references/modeling-recipes.md) 选择角色与配方。

1. 将真实入口保存为 `code/matlab/run_analysis.m`。输入只来自 `problem/`、受控参数或明确登记的 current 结果；脚本通过 `SHUMOZIZI_RUN_DIR` 定位运行根目录，不使用仓库外绝对路径。
2. MATLAB 至少承担一种科学角色：`primary_model`、`optimizer_challenger`、`independent_oracle` 或 `scientific_visualization`。不能只把 Python 数组导出后重算平均值。独立实现不得导入、翻译或调用 Python 核心判定函数；可共享原始输入和最终问题定义，不共享中间数组与判定源码。
3. 每次启用必须真实产生 `results/matlab/result.json`、`result.csv`、`figures/current/matlab-*.pdf`、`matlab-*.png` 和 `logs/matlab-run.log`。统一执行：`python scripts/matlab/run_matlab.py <run_dir> --config <config.json>`；底层命令为 `matlab -batch "run('code/matlab/run_analysis.m')"`。
4. 运行器写 `results/matlab/manifest.json`，记录入口、版本、真实工具箱、输入、输出、耗时和退出状态，并把成功执行登记为 current 生产结果。环境不可用时必须写 `availability=unavailable` 和失败结果，不生成假输出或假回执。
5. MATLAB 专有优化器只在 manifest 中确实记录相应工具箱且许可证可用时使用；否则选择基础 MATLAB 可实现的枚举、矩阵算法、数值积分或明确的 Python fallback。Octave 不得声称支持 MATLAB 专有工具箱。
6. 结果 JSON 应同时输出最终指标和模型原生视觉数据，如候选解、可行边界、活跃约束、搜索历史、Pareto 点、状态轨迹或不确定性样本。科学图必须基于同次执行的真实结构数据，标出最优点、边界、baseline/fallback 和结论所需的关键事件。
7. `method_profile.stochastic=true` 才要求 multiseed；`uses_proxy_objective=true` 才要求 proxy-exact。MATLAB 的存在不自动触发风险，也不证明独立性或正确性。出现更优候选、复算冲突或不可行证据时，按负面证据规则级联失效旧结果、图和论文。

Windows 示例：

```powershell
matlab -batch "run('code/matlab/geometry_oracle.m')"
octave --quiet --no-gui code/matlab/geometry_oracle.m
```

若引擎不存在，保留 runner 生成的 unavailable manifest，并在 `DECISIONS.md` 记录替代实现与独立性边界；不要静默降为复用 Python 的同源 oracle。
