# 第三方来源说明

## MathModelAgent Skills

`skills/` 目录来自：

- 项目：`jihe520/MathModelAgent`
- 地址：https://github.com/jihe520/MathModelAgent
- 对照提交：`be9c59c1aaa13c3dcb74452ea5cae11dada27589`
- 获取日期：2026-07-19

该上游提交的仓库根目录未发现明确的 `LICENSE` 文件。保留本目录是为了能力基线、来源追踪
和后续同步；不要仅依据本仓库根目录的 MIT 文件，推定上游材料已被重新许可。

## 本仓库新增部分

`.agents/skills/`、`schemas/`、`scripts/codex/`、`.codex/config.toml` 以及 Codex 工作流文档
是本仓库新增的适配层。未直接复制参考项目的算法库、论文库、重型评审协议或应用代码。

## 选择性外部能力来源

### Lupynow/math-modeling-skills

- 地址：https://github.com/Lupynow/math-modeling-skills
- 固定提交：`856816bda312ca9c02082f1d026d1416ebbaa861`
- 许可证：仓库根无总许可证；本次研究范围内的
  `skills/math-modeling-solver/` 与 `skills/math-modeling-paper/` 分别声明 MIT
- 使用范围：模型选择知识卡、算法目录思想、四个本地独立实现模板的来源语境。
- 未引入：上游工作流、状态机、审批逻辑和整套 Skills。

### handsomeZR-netizen/mathmodel-skill

- 地址：https://github.com/handsomeZR-netizen/mathmodel-skill
- 固定提交：`b1584e6aa3f05141abf0143575e02005f14bd2ef`
- 许可证：当前固定提交的仓库根未发现许可证文件
- 使用范围：只研究 Friendly Mode 与比赛 Profile 的抽象交互思想；没有复制代码、模板或文字资产。
- 未引入：上游十阶段工作流、decision log、评分 verdict 或第二套控制面。

### sweetcornna/mathodology

- 地址：https://github.com/sweetcornna/mathodology
- 固定提交：`987644876160d105f0fa768248f5d23764f288b2`
- 上游声明许可证：MIT
- 使用范围：有界修复、图表碰撞回执、PDF 与提交包机械检查的设计思想和独立 Adapter。
- 未引入：三席评审、九阶段工作流、第二套状态机或自动获奖结论。

### NeoXue-ai/math-modeling-solver

- 地址：https://github.com/NeoXue-ai/math-modeling-solver
- 固定提交：`a24b8b88385bf3fb846a0e40ddc0a771c37d8f40`
- 上游声明许可证：MIT
- 使用范围：结果到论文的追踪思想和独立 evidence audit Adapter。
- 未引入：第二套结果注册表、重型质量门或额外人工 checkpoint。

### jihe520/MathModelAgent-Example

- 地址：https://github.com/jihe520/MathModelAgent-Example
- 固定提交：`4251c4dec7026ac94132628079f814f3c9c37a3e`
- 许可证：当前固定提交的仓库根未发现许可证文件
- 使用范围：仅研究作者预期的运行产物形态，不作为质量基准且不复制资产。

来源契约的机器可读版本位于 `knowledge/SOURCE_REGISTRY.json`。所有来源均已唯一定位并锁定
提交；许可证未声明的仓库仅允许研究不受版权保护的抽象思想。
