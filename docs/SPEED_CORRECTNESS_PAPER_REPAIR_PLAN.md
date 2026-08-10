# 数学建模工作流提速、正确性与论文表现修复计划

## 1. 计划结论

本计划不把外部工作流当作答案库，也不复制其参数、数值、代码或结论。对照的目的只有两个：

1. 保留本项目在目标语义、统一评分、结构不确定性、独立复算和证据边界方面的优势。
2. 学习外部论文在直接回答、图文节奏、结果可见性和一次性成稿方面的优点，把低风险任务从“全量深审”改为“风险触发”。

最终目标是在不降低科学硬门的前提下，把普通赛题从长时间串行迭代改造成三小时内可形成有竞争力候选稿、只有出现真实高风险证据时才进入深挖的双速工作流。

## 2. 对照材料与项目入口

### 2.1 外部工作区

- [外部最终论文](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/document.pdf)
- [外部主 LaTeX 文件](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/document.tex)
- [外部固定折射率假设](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/texfile/4AssumptionAndSign.tex)
- [外部误差分析](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/texfile/6ErrorAnalysis.tex)
- [外部手工误差预算代码](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/code/q4_analysis.py)
- [外部 Q2 结果](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/results_q2.json)
- [外部 Q3 结果](C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/results_q3.json)

### 2.2 本项目与同题运行

- [项目 README](../README.md)
- [Competition-First 项目约定](../AGENTS.md)
- [本项目同题论文](../runs/cumcm-2025-b-sic-20260729/paper/main.pdf)
- [同题正式答案映射](../runs/cumcm-2025-b-sic-20260729/analysis/answer_map.json)
- [同题科学挑战报告](../runs/cumcm-2025-b-sic-20260729/review/SCIENTIFIC_CHALLENGE.md)
- [同题结果索引](../runs/cumcm-2025-b-sic-20260729/results/index.json)

### 2.3 计划涉及的核心模块

- [完整工作流 Skill](../.agents/skills/mathmodel-workflow/SKILL.md)
- [分析与路线竞争 Skill](../.agents/skills/mathmodel-solve/SKILL.md)
- [实验 Skill](../.agents/skills/mathmodel-experiment/SKILL.md)
- [高级图与视觉沙盒 Skill](../.agents/skills/mathmodel-visual/SKILL.md)
- [论文写作 Skill](../.agents/skills/mathmodel-paper/SKILL.md)
- [科学红队 Skill](../.agents/skills/mathmodel-red-team/SKILL.md)
- [实验命令行入口](../scripts/runtime/run_simple_experiment.py)
- [实验执行实现](../src/shumozizi/simple/execution.py)
- [结果登记与 provisional 逻辑](../src/shumozizi/simple/results.py)
- [首次可行解检查](../scripts/review/show_first_feasible_prompt.py)
- [视觉要求生成](../src/shumozizi/paper/visual_requirements.py)
- [Author Pass 入口](../scripts/paper/prepare_longform_author.py)
- [论文风格审计](../scripts/paper/audit_report_style.py)

## 3. 谁的哪里好

| 能力 | 外部方案做得好的地方 | 本项目做得好的地方 | 最终采用方式 |
|---|---|---|---|
| 启动速度 | 固定主要假设后快速形成 Q1–Q3 脚本和完整论文；工作区生成窗口约 54 分钟 | 会先澄清目标、聚合方式、共享对象和问题继承 | 保留本项目的题意硬门，但将普通诊断标为 exploration，不进入正式结果链 |
| 直接回答 | 摘要按问题逐项给出方法和数值，读者很快找到结果 | 能区分 objective answer、条件答案、建议和证据等级 | 用本项目的正确答案边界，采用外部的“摘要直接报答案”写法 |
| 页面节奏 | 大图、彩色图、结果表频繁穿插，读感像竞赛论文 | 图表均来自真实 current 结果，能追溯到 scorer 和脚本 | 保留真实数据约束，增加 Hero 图并提高关键图视觉权重 |
| 机制解释 | 会使用流程图、频谱图、灵敏度图和最终汇总图解释模型 | 能解释补偿带、活跃约束、留出收益和结构不确定性 | 用本项目机制，采用外部“每个关键主张后立即给图”的节奏 |
| 可靠性表达 | 单独设置误差与可靠性章节，读者容易看到 | 分清 bootstrap 随机区间、结构范围、模型选择和独立复算 | 保留分层不确定性，改造成一张统一总结图，禁止混成单一误差条 |
| 模型选择 | 会比较两光束和 Airy，而不是只跑单模型 | 使用共同色散网格、共同留出块、共同 scorer 和事前门槛 | 完全采用本项目判定方法；外部只贡献“比较结果要可视化”的表达方式 |
| 科学边界 | 会在误差分析中承认固定折射率可能产生显著偏差 | 真正把该偏差升级为结构不可辨识攻击，并限制论文主张 | 采用本项目；不能把外部固定折射率结果写成无条件绝对厚度 |
| 误差预算 | 有直观的误差预算图 | 扰动结果可由真实实验复算和追溯 | 学外部图形，不学其手填数组；所有条目必须由结果文件生成 |
| 工程可复现 | 目录简单，脚本和结果易找到 | 有生产结果、来源哈希、独立实现、current/archive 和失效规则 | 对用户输出保持简单目录；复杂审计留在后台，不进入论文叙事 |
| 最终呈现 | 有目录、结论汇总、附录和代码页，形式完整 | 代码附件与论文正文边界更合理，不用代码页数填充篇幅 | 不复制两页目录和两页代码；使用一页以内紧凑导航和电子附件 |

### 3.1 明确学习外部方案的内容

- 摘要第一屏直接给出各问方法、关键数值和模型选择。
- 每个核心结论附近立即出现对应图或结果表。
- 主要图宽度接近正文宽度，字号、图注和单位在打印状态下可读。
- 用一张最终汇总图回收全篇结果，而不是只在结论中堆数字。
- 让普通读者先理解问题、数据和结论，再进入完整推导。

### 3.2 明确不能学习外部方案的内容

- 不能把固定折射率下的数值当成无条件绝对厚度。
- 不能用训练拟合、频谱峰或单个局部改进代替留出验证。
- 不能把手工填写的误差预算画成实验结果。
- 不能因“图多”就把解释型合成图当作结果证据。
- 不能因工作区生成快就省略统一 scorer、硬约束、可辨识性和反例检查。
- 不能宣称某种物理机制绝对不存在；只能声明在测试的数据和模型族内未获得稳定收益。

## 4. 当前根因

同题运行共有 35 条结果记录，其中 13 条被替换、6 条失败；所有实验的实际计算时间合计约 21.58 分钟，但结果时间跨度约 34.75 小时。计算占墙钟时间约 1%，因此主要瓶颈不是 MATLAB、Python 或优化器，而是：

1. 探索实验默认进入 production 语义，导致每次调整都触发结果替换和后续失效。
2. 高风险语义、可辨识性和模型选择攻击发现得太晚，迫使模型、结果、图和论文多次返工。
3. 图表在科学事实冻结前反复进入正式视觉链，造成重复渲染和审图。
4. 审查、写作和绘图以串行方式发生，简单题和高风险题承担近似相同的流程成本。
5. 论文保留了大量研究过程，却没有把最有竞争力的发现提升为前五页的视觉主线。

## 5. 目标工作流

```text
analysis
  ├─ 题意与数据指纹
  ├─ 自然 baseline
  ├─ 最高风险性质测试 / 最小反例 / 可辨识性快攻
  └─ 决定进入快速路线或深化路线

experiment
  ├─ exploration：baseline + 一条结构不同的 challenger
  ├─ 统一 scorer 与共同预算
  ├─ 风险触发的深化、oracle、敏感性
  └─ 冻结后少量 production 重跑

paper
  ├─ 结果与主张边界冻结
  ├─ 高级 Hero 图竞争
  ├─ 前五页答案与证据链
  └─ 长篇 Author Pass

paper_review -> verify -> complete
```

六阶段主链保持不变。快速路线与深化路线只是 `analysis` 和 `experiment` 内部的风险分流，不新增协议阶段。

## 6. 分阶段实施计划

### 阶段 A：建立 exploration 与 production 的真正边界

**优先级：P0；预计 0.5–1 天；负责人模块：runtime/results。**

#### 修改

1. 在 [run_simple_experiment.py](../scripts/runtime/run_simple_experiment.py) 增加：

   - `--execution-mode {exploration,production}`；
   - `--provisional`；
   - exploration 默认 `provisional=true`；
   - production 默认 `provisional=false`。

2. 把参数传递给 [execute_simple_experiment](../src/shumozizi/simple/execution.py)，复用已有 provisional 能力。

3. exploration 成功结果不得：

   - 替换 current production incumbent；
   - 使正式图和论文失效；
   - 被 answer-map 或 Author Pass 选为正式答案。

4. 不提供“无重跑提升”为正式结果的捷径。候选胜出后必须以 production 模式重新执行，从源数据生成正式产物。

#### 验收

- 增加 CLI 回归测试，验证 exploration 不替换 current production。
- 复用并扩展 [test_verification_protocol.py](../tests/test_verification_protocol.py) 中 provisional 测试。
- 同一候选连续运行五次 exploration，正式 answer-map、current 图和论文状态均不变化。
- production 重跑后，结果、输入哈希、命令和输出均可追溯。

### 阶段 B：把最高风险攻击提前到第一次正式搜索之前

**优先级：P0；预计 1 天；负责人模块：solve/experiment。**

#### 修改

在 `analysis` 内为每个核心问题生成一个“最低成本风险包”，但不新增阶段：

1. 逆问题： nuisance 参数—目标量 profile、近优集合和参数补偿带。
2. 多角度或多主体问题：分别求解再组合的最小反例。
3. 时间序列：连续留出块或滚动留出，禁止随机点泄漏。
4. 模型复杂度比较：共同数据窗口、共同划分、共同 scorer、共同预算和事前收益门槛。
5. 优化问题：3–5 个人工案例验证 scorer 排序，再运行 baseline。

#### 输出

- 风险结论写入现有 `MODELING_UNITS.json`、`OBJECTIVE_CANDIDATES.json` 或 `BASELINE_FREEZE.json`，不创建新的状态门文件。
- 明确生成三类主张标签：`unconditional`、`conditional_on_assumption`、`sensitivity_only`。
- 任一结构攻击推翻唯一性时，论文结果自动转为条件结果或范围，不允许只在局限性中补一句。

#### 验收

- 在 SiC 回归夹具中，第一次 production Q2 之前即发现厚度—折射率补偿关系。
- 在 Q3 第一次正式选模之前即使用共同留出 scorer 比较 two-beam 与 Airy。
- 固定折射率结果不能通过 `unconditional` 主张检查。
- 最高风险包总运行时间目标小于 15 分钟；超时只形成提示，不牺牲正确性。

### 阶段 C：采用风险触发的双速实验路线

**优先级：P0；预计 0.5 天；负责人模块：workflow/experiment。**

#### 快速路线进入条件

- 目标与聚合解释唯一或已通过最小反例。
- baseline 与 challenger 的共同 scorer 已建立。
- 没有结构不可辨识、分解失效、硬约束冲突或数据泄漏证据。
- challenger 已停止快速改善，或 baseline 有合理上界证据。

#### 深化路线触发条件

- 两个合法目标解释产生不同主结果。
- nuisance profile 出现宽补偿带或多峰近优集合。
- challenger 仍快速改善或达到显著收益。
- 留出结果与训练结果方向相反。
- independent oracle、硬约束或性质测试冲突。

#### 停止规则

- 普通问题：一个 baseline、一个自然比较、一个关键验证即可。
- 核心优化/协同问题：baseline 加一条数学结构不同的 challenger；只有仍不确定时再增加第二条。
- 不把 GA、PSO、DE 的简单替换计为三条独立数学路线。
- 每次新增实验必须写预期决策价值；不能改变路线、主张边界或推荐方案的实验不进入生产预算。

#### 验收

- 低风险夹具从初始化到 production 结果目标不超过 90 分钟。
- 高风险夹具允许继续深化，但必须能说明具体触发证据。
- 同题运行中 superseded 结果比例目标从 37% 降到 15% 以下。
- 失败运行不超过全部正式运行的 10%；探索失败不污染正式结果索引。

### 阶段 D：结果冻结后再启动高级图竞争

**优先级：P1；预计 1 天；负责人模块：visual/paper-image。**

高级图是必要交付，不以减少图数为优化目标。优化的是图的论证价值和出现时机。

#### 视觉层级

1. **Hero 图**：2–3 张，承担决定性结论，至少一张在前五页出现。
2. **Supporting 图**：解释模型、数据和关键诊断，按论证需要增加。
3. **Stability 图**：完整保留在附录，不与主结论抢视觉权重。

#### SiC 同题的推荐 Hero 图

1. `数据 → 共享相位 → 模型判别` 三联证据链：原始双角度光谱、SiC 补偿脊、Airy 收益与判定阈值。
2. `折射率—厚度可辨识性地图`：近优集合、名义点、最远近优点、条件区间和结构范围。
3. `模型选择收益地图`：共同色散网格上的 Airy 留出收益、10% 门槛、退化边界和稳定解数量。
4. `最终不确定性分层`：SiC 的条件随机区间与结构范围、Si 的块长敏感性包络，不把不同来源误差混成同一置信区间。

#### 绘图合同

- 主图使用真实 current 数据和正式 renderer 重生成。
- 关键图正文宽度建议为 0.85–0.98 `\textwidth`，最终 PDF 最小文字不低于 8 pt。
- 每张关键图必须回答：观察、机制、决定、边界。
- 色盲与灰度打印可区分；颜色、标记、线型至少使用两种通道。
- 图中直接标出名义点、近优集合、阈值、赢家和无效区域。
- 不把合成解释图、训练拟合或收敛曲线单独作为正确性证据。

#### 与当前视觉改动的关系

当前仓库已有未提交的 `mathmodel-paper-image`、visual sandbox 和 figure template 改动。阶段 D 不覆盖这些文件；先完成现有改动的独立测试，再把 Hero 图层级、前五页位置和真实数据重生成合同接入。相关入口包括：

- [mathmodel-visual](../.agents/skills/mathmodel-visual/SKILL.md)
- [视觉要求生成](../src/shumozizi/paper/visual_requirements.py)
- [论文图像工作流测试](../tests/competition_first/test_paper_image_workflow.py)
- [图表模板适配说明](V3_FIGURE_TEMPLATE_ADAPTER.md)

#### 验收

- 前五页至少出现一张决定性高级图，而不是只有路线图和原始数据图。
- 冷读者在三分钟内能指出主图及其支持的论点。
- 所有正式图都有 current 结果来源；结果变化时能正确失效。
- Hero 图与普通诊断图在尺寸、布局和图注上有明确层级差异。

### 阶段 E：把论文从研究报告改成答案优先的竞赛叙事

**优先级：P1；预计 1 天；负责人模块：paper/author-pass。**

#### 前五页合同

1. 第 1 页摘要：按“问题链—条件结果—模型判定—验证边界”组织。
2. 第 2 页：三问直接答案表和一张共享对象路线图。
3. 第 3 页：原始数据直觉和分析窗口。
4. 第 4–5 页：Hero 图预告最重要的结构发现和模型选择，不等待第 12、15 页才出现。

#### 正文章节合同

每个问题采用：

```text
直接答案 -> 数学对象与关键推导 -> 决定性证据 -> 机制解释 -> 有效边界
```

- 不要求机械固定每问小节，但每问必须能在三分钟内定位直接答案。
- 共享推导集中一次说明，后续问题只写新增实体、约束和判据。
- 公式服务于判断，不按求解时间顺序记录全部研究过程。
- 贡献最多三项，优先写共享相位坐标、结构可辨识性和统一留出选模；不把常规算法组合包装成创新。
- 参考文献目标约 9–12 篇经过核验的来源；数量为紧凑建议，不是硬门。
- 目录若赛事或模板需要，控制在一页内；完整代码作为电子附件，正文代码不超过一页。

#### 验收

- 摘要中的所有数值与 answer-map/current production 一致。
- 摘要明确区分条件区间与结构范围。
- 第 2 页直接答案表能独立回答 Q1–Q3。
- Cold Reader 能复述一句话贡献、指出主图、找到每问直接答案和工作报告页。

### 阶段 F：机械格式与出版质量修复

**优先级：P1；预计 0.5 天；负责人模块：paper/final-check。**

#### 检查项

- 使用至少两个 PDF renderer 抽查所有页，重点复验当前渲染中第 15、17、19、21 页页码前导数字缺失现象。
- 检查中文字体嵌入、公式字体、图中最小字号、黑白打印和 A4 页面裁切。
- 自动检测大面积非意图留白；第 17 页的表与图优先重新分页。
- 参考文献页与附录重新分页，避免七条文献占据整页后留下大面积空白。
- 检查图题、表题、单位、交叉引用和正文首次引用顺序。
- 源码附录遵守默认一页预算，完整程序进入附件。

#### 验收

- PDF 任一页不存在缺失页码、裁切、重叠、文字越界或不可读图注。
- 所有图在 100% A4 视图下可读，在灰度打印下仍能区分关键系列。
- 机械 QA 只验证交付正确性，不替代独立科学挑战和 PDF 冷读。

### 阶段 G：用评测证明“更快且不降级”

**优先级：P0；预计 1–2 天；负责人模块：evaluation。**

#### 评测集

至少选择三类已有离线夹具：

1. 低风险固定评价或数据建模题。
2. 带 nuisance 参数和结构不可辨识风险的逆问题。
3. 核心优化或协同题。

不得通过联网寻找同题答案或现成结论。

#### 对照组

- A：当前 Competition-First v3.4 工作流。
- B：加入 exploration 边界、早期风险包、结果冻结和 Hero 图合同后的工作流。

#### 指标

| 维度 | 指标 | 通过标准 |
|---|---|---|
| 速度 | 首个可行结果时间 | B 不劣于 A，低风险题目标小于 45 分钟 |
| 速度 | candidate PDF 时间 | 低风险题目标小于 180 分钟 |
| 返工 | superseded production 比例 | 目标低于 15% |
| 正确性 | 错误注入检出率 | 不低于当前基线 |
| 正确性 | 高风险反例发现时机 | 在首次 production 结果前发现 |
| 竞争力 | 匿名 PDF pairwise | B 在直接性、主图、前五页数据直觉上胜出 |
| 可追溯 | 数字、图和 answer-map 绑定 | 100% 通过 |
| 视觉 | 三分钟主图识别 | 冷读者能指出主图及其论点 |

#### 停止条件

- 若 B 提速但漏掉 A 能发现的 P0/P1 科学错误，则不能发布，必须回到阶段 B/C。
- 若正确性相同但视觉 pairwise 无提升，则回到阶段 D/E，不增加无决策价值的实验。
- 若视觉提升但总耗时仍高，继续检查 production churn 和串行审查，不删除科学硬门。

## 7. 推荐实施顺序与里程碑

| 里程碑 | 工作内容 | 依赖 | 完成定义 |
|---|---|---|---|
| M1 | exploration/provisional CLI 与测试 | 无 | 探索结果不污染 current production |
| M2 | 早期风险包与主张分级 | M1 | SiC 回归在首次 production 前发现补偿带 |
| M3 | 双速实验路由与停止规则 | M1、M2 | 低风险题能快速结束，高风险题有证据触发深化 |
| M4 | Hero 图合同与前五页视觉层级 | M2、现有视觉改动稳定 | 关键图进入前五页且绑定 current 数据 |
| M5 | 答案优先 Author Pass | M2、M4 | 摘要、直接答案表、主图和边界一致 |
| M6 | PDF 机械修复与 A/B 评测 | M3、M5 | 正确性不下降，速度和匿名阅读显著改善 |

推荐先完成 M1–M3，再进入 M4–M6。不要先大规模改模板；否则实验结果和叙事边界变化后会再次重画。

## 8. 三小时竞赛目标节奏

该节奏是优化目标，不是正确性豁免：

| 时间 | 目标产物 |
|---|---|
| 0–15 分钟 | 题面指纹、数据审计、每问直接答案合同、最高风险列表 |
| 15–45 分钟 | baseline、人工 scorer 案例、首次可行结果 |
| 45–75 分钟 | 一条结构不同 challenger、可辨识性/分解/泄漏快攻 |
| 75–120 分钟 | 统一留出评分、必要敏感性、路线冻结 |
| 120–150 分钟 | 少量 production 重跑、answer-map、结果汇总 |
| 150–180 分钟 | Hero 图、前五页、长篇草稿骨架 |
| 之后 | 一次科学挑战、一次 cold read、一次机械 QA；仅按真实 finding 返工 |

如果 75 分钟前出现目标歧义、结构不可辨识、oracle 冲突或 challenger 持续改善，自动退出三小时快速目标并进入深化路线，不能为了速度压掉负面证据。

## 9. 最终验收清单

### 求解与正确性

- [ ] 最高风险性质测试在首次 production 前完成。
- [ ] baseline 与 challenger 使用共同 scorer、共同数据和共同预算。
- [ ] 训练拟合与连续留出结果明确区分。
- [ ] 条件结果、结构范围和敏感性结果不混写。
- [ ] 误差预算全部来自真实运行产物。
- [ ] 独立复算角色清楚，不能与主实现共享关键闭包后冒充独立。

### 速度与工程

- [ ] exploration 不替换 current production。
- [ ] 正式结果数量小而稳定，superseded production 比例低于目标。
- [ ] 视觉和论文只消费冻结后的正式结果。
- [ ] 低风险题不因可选元数据或重复审查被阻断。
- [ ] 审查次数由真实 finding 决定，不循环追求“全绿”。

### 高级图与论文

- [ ] 前五页至少一张决定性 Hero 图。
- [ ] 每张关键图都能回答观察、机制、决定和边界。
- [ ] 每问直接答案可在三分钟内找到。
- [ ] 摘要和最终汇总表绑定同一 primary result。
- [ ] 正文图没有使用 synthetic 数据替代当前结果。
- [ ] PDF 页码、字体、留白、图注和灰度打印通过机械复验。

## 10. 最终取舍

外部方案最值得学习的是“快、直接、大图、结果靠前”；本项目最不能丢的是“目标正确、统一评分、结构攻击、独立复算、主张有边界”。最终版本必须同时满足：

> 用外部方案的表达效率，呈现本项目更可靠的科学证据；用风险触发替代全流程堆叠，但不使用速度替代正确性。
