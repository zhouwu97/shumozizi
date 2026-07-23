# 第三方来源说明

## MathModelAgent Skills

`skills/` 目录来自：

- 项目：`jihe520/MathModelAgent`
- 地址：https://github.com/jihe520/MathModelAgent
- 对照提交：`be9c59c1aaa13c3dcb74452ea5cae11dada27589`
- 获取日期：2026-07-19

该上游提交的仓库根目录未发现明确的 `LICENSE` 文件。保留本目录是为了能力基线、来源追踪
和后续同步；不要仅依据本仓库根目录的 MIT 文件，推定上游材料已被重新许可。v3 仅按需使用
其中已保留的 `2analysis-modeling`、`3coding-visual` 与 `mathmodel-figure-templates` 作为能力资产；
科研绘图模板中的模拟数据只允许用于布局演示。v3 的独立适配器仅为四个模板提供真实 JSON 输入，
并把来源、输出和哈希登记到当前运行；其余保留模板不得作为当前论文证据。

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
- 使用范围：有界修复、图表碰撞、PDF 与提交包机械检查的设计思想；v3 的
  `tools/qa/` 为 Windows 可运行的独立实现，未复制上游源文件。
- 未引入：三席评审、九阶段工作流、第二套状态机、图表回执或自动获奖结论。

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

### Capability-First v3 知识资产导入

以下来源在 2026-07-22 通过其固定提交的许可证文件核验。本次仅写入原创、事实性的能力卡；
没有复制代码、notebook、段落、工作流、状态机或质量协议。

- `Pyomo/pyomo`：https://github.com/Pyomo/pyomo ，提交
  `b953cf90d6ed26df46cb5924301a89e2e76716fa`，`LICENSE.md`，BSD-3-Clause；用于结构化优化
  的变量/目标/约束和结构识别事实。
- `jckantor/MO-book`：https://github.com/jckantor/MO-book ，提交
  `d28bce00231c6327d47ea85d3fe4782f9092ccd9`，`LICENSE`，MIT；用于代数优化、松弛和分解的
  建模事实。
- `anyoptimization/pymoo`：https://github.com/anyoptimization/pymoo ，提交
  `23110c155aa8f31b5f1b86928227fb3931ba7f00`，`LICENSE`，Apache-2.0；用于非光滑、稀疏与
  多目标搜索的算法族事实。
- `SALib/SALib`：https://github.com/SALib/SALib ，提交
  `aa2c5545b3bfd0a982e9fad7625070a8ea340d38`，`LICENSE.md`，MIT；用于敏感性诊断与不确定性
  报告事实。
- `Lupynow/math-modeling-skills`：沿用已登记提交
  `856816bda312ca9c02082f1d026d1416ebbaa861`；目标 `math-modeling-solver` 目录的 `LICENSE`
  为 MIT。本次只借助其模型选择问题域，不引入其控制逻辑。

### 选择性 vendored 能力包（2026-07-23）

这些资产位于 `vendor/`，不会作为第二套总控工作流自动发现。每个目录的 `SOURCE.json` 记录固定提交、导入路径和本地修改；许可证原文随资产保留。

- `Yuan1z0825/nature-skills`，提交 `91862221b39f7ca16d52ae0e1e9cb6c2bb31a96b`，Apache-2.0：仅导入 `skills/nature-figure`，用于多面板、统一导出和图形 QA 底座。
- `K-Dense-AI/scientific-agent-skills`，提交 `831d49eb77eed3c792be2970921b46764012ef00`，MIT：仅导入 `pymoo`、`sympy` 和 `scientific-visualization`。
- `Boom5426/Nature-Paper-Skills`，提交 `e6f0448271250072bc880aef91311a64e3473981`，MIT 与 Apache-2.0 混合来源：仅导入 `figure-planner`、`manuscript-optimizer` 和 `stats-reporting-audit`，保留上游 `NOTICE`；不导入 `paper-workflow`。
- `Lupynow/math-modeling-skills`，提交 `856816bda312ca9c02082f1d026d1416ebbaa861`，目标目录 MIT：仅导入 solver/paper 的 `references`，包括 `code-templates` 与 `playbooks`；不导入 `SKILL.md`、阶段控制或写作总控。
