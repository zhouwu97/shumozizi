# MATLAB 建模、优化与科学绘图配方

## 能力路由

| 问题结构 | 首选能力 | 启用前检查 |
| --- | --- | --- |
| 连续/非线性优化 | `fmincon`、`patternsearch`、`particleswarm`、`ga` | 目标/约束可独立实现；Optimization/Global Optimization Toolbox 可用 |
| 整数规划 | `intlinprog` 或基础枚举/分支限界 | 变量、界和整数索引明确；Optimization Toolbox 可用 |
| 多目标优化 | `gamultiobj` 或 exact 枚举后 Pareto 筛选 | 两目标方向、硬约束和折中规则预先声明 |
| ODE/刚性系统 | `ode45`、`ode15s` | 单位、初值、事件函数和守恒/残差检查明确 |
| PDE/场 | PDE Toolbox 或离散有限差分/有限元 | 边界条件、网格收敛和工具箱真实可用 |
| 矩阵/谱 | 稀疏矩阵、`eig/eigs`、SVD/QR | 条件数、尺度和截断规则有记录 |
| 信号 | FFT、滤波、频谱、小波 | 采样率、窗函数、泄漏和 Signal Toolbox 可用性明确 |
| 图像 | 分割、形态学、几何变换 | 像素尺度、评价真值和 Image Processing Toolbox 可用 |
| 拟合 | `fitlm`、`fitnlm`、样条 | 重复测量、残差、外推边界和 Statistics Toolbox 可用 |
| 控制/仿真 | 状态空间、控制器、Simulink | 状态/控制量、稳定性判据和工具许可明确 |
| 三维几何/场 | `surf`、`contour3`、`isosurface`、`streamline`、`plot3` | 3D 维度有数学含义，另给剖面或投影 |
| 网络 | `graph`、`digraph`、`shortestpath`、`maxflow` | 边方向、容量、权重和连通性语义明确 |

## 四种角色

### 主建模器

MATLAB 直接从原始输入建立优化、动力学、信号、空间或拟合模型。JSON 保存指标、决策变量、约束余量和视觉结构数据；CSV 保存可复算的候选/轨迹表。

### 独立优化器 challenger

与 Python 共享原始输入和 exact 目标定义，不共享候选数组、搜索历史或核心搜索源码。使用结构不同的算法族，比较最优值、可行率、预算、稳定性和策略结构。若 challenger 更优，按负面证据处理旧 incumbent。

### 独立 oracle

从题意重新推导另一种判定：几何可用二次方程交点对照投影裁剪，动力学可用不同积分器和步长并检查守恒，组合问题可用小实例枚举对照启发式。文件扩展名不同不算独立。

### 独立科学图

MATLAB 从原始或登记结果独立生成三维场景、剖面、Pareto、可行域、向量场、轨迹或频谱；图仍需绑定 current 生产结果，不能以渲染成功代替科学验证。

## 统一入口

入口头部写清输入、单位和命令，并只通过环境变量定位运行目录：

```matlab
runDir = getenv('SHUMOZIZI_RUN_DIR');
assert(strlength(runDir) > 0, 'SHUMOZIZI_RUN_DIR is required');
inputPath = fullfile(runDir, 'problem', 'attachments', 'input.xlsx');
resultDir = fullfile(runDir, 'results', 'matlab');
figureDir = fullfile(runDir, 'figures', 'current');
```

执行配置必须声明 `entrypoint`、`question_id`、`result_id`、`role`、`input_files`、四类 `output_files`、`metric_sources` 和 `objective_semantics_sha256`。运行：

```powershell
python scripts/matlab/run_matlab.py runs/<run-id> --config runs/<run-id>/code/matlab/run-config.json
```

## 高价值绘图模板

第一批只覆盖十类：三维场景+最优方案、曲面+等高线投影、几何剖面、Pareto 前沿、搜索轨迹双面板、可行域+约束激活、时间着色轨迹+事件带、不确定性扇形、参数→动作决策面、2--4 面板证据链。每张图必须标注最终点、边界/阈值和 baseline/fallback；配色、3D 或子图数量本身不计为信息价值。

