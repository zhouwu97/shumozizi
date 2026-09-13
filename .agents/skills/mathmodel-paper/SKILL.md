---
name: mathmodel-paper
description: 从当前正式结果组织、编译和修订数学建模论文；优先中心论点、机制解释和自然学术表达，不把运行审计写进正文。
---

# 论点优先的论文工作流

论文首先回答“研究发现了什么、为什么会这样、在什么条件下成立”，再说明技术细节。运行状态、哈希、回执、gate、repair、coordinator、scorer 和线程信息属于后台，不进入作者材料或正文。

## 写作输入

Author 默认只读取：

- `paper/author-pass/RESEARCH_PACKAGE.md`
- `paper/author-pass/AUTHOR_BRIEF.md`
- `paper/author-pass/THESIS_CARD.md`
- 已关闭的高价值科学意见

Research Package 必须包含数学对象、关键推导、约束物理意义、模型选择理由、baseline/challenger 对比、代表性反例、机制发现、敏感性边界、正式答案和图解读。不要机械截断材料，也不要把后台字段逐项转写成小节。

写作启动前运行 `python scripts/simple/build_production_manifest.py check <run_dir>`；它只确认每问唯一正式结果和当前结果索引一致，不把 manifest 内容写入正文。

写作前由 Author Pass 生成 `THESIS_CARD`：一句中心矛盾、最多三项贡献、每问一个机制判断、正式答案、证据边界和主图候选。作者先用它确定读者阅读路径，再决定章节；问题可以合并或调整顺序，不能为了模板完整而平均分配篇幅。

## 成文顺序

```text
数据结构发现 → 核心矛盾 → 共享数学对象 → 模型选择与推导 → 理论预测 → 受控实验 → 机制 → 边界
```

摘要先给问题困难、统一结构、关键方法、主要发现和适用条件；正文使用连续学术段落。开篇先写数据中真正改变建模选择的结构事实，而不是罗列均值、峰值和文件大小。逐问答案要容易定位，但不要写成“本问完成了……随后验证了……”的工作报告。

每个核心结论尽量形成一条研究叙事：数据发现提出问题，简化理论给出可检验预测，完整模型检验预测并暴露边界，受控实验解释偏离的机制，最后把机制转成题目要求的决策。理论只要能产生可反驳的方向、阈值或排序就有价值，不要求把复杂系统强行化成闭式解。

开放题先拆成可直接测量的变化轴与只能给上界或反事实的变化轴；每条轴设置自然 baseline、一个明确的 challenger、共同评价窗口和停止条件。结果要同时报告收益、机制和信噪比：差异小于实现不确定度时写“无法区分”，不要把随机波动包装成方向性结论。

图表沿用“先结论、后证据”的写法：先写这张图要证明什么，再选择最清楚的编码；同一判断需要直接比较的面板可以合并，互不支撑同一判断的图不要硬拼。图后解释观察、机制和结论，图注保持短句。正文不出现 `current`、`result_id`、`execution_valid`、`P0/P1`、`scorer`、`challenger`、`coordinator` 等控制层术语；必要的复现信息放在附录或提交包。

## 编译与返修

先独立生成 `paper/longform-source.tex` 或 `.typ`，再运行：

```powershell
python scripts/paper/prepare_longform_author.py <run_dir>
python scripts/paper/compile_longform_draft.py <run_dir>
```

首稿后做一次冷读和一次 Editorial Pass。Editorial Pass 先检查前五页是否建立问题直觉、答案和主图，再删掉报账句式、合并重复限制、增强机制解释和调整图文节奏，不新增表单或人为扩写。只有科学事实变化才返回 experiment/analysis；数字、图、表和 Excel 不来自同一 `production_manifest` 时阻断。

图数、页数、标题样式、列表密度和视觉 archetype 都是编辑信号。旧 `competition-quality-v1` 运行可继续执行旧数量合同，新 `science-editorial-v1` 运行不设逐问或全篇图数硬门。

## 论文硬门

1. 每个必答问题有正式 `objective_answer`；
2. 全部数字、图、表、Excel 来自同一个正式 manifest；
3. 已证实科学错误和越界强主张已关闭；
4. 论文能在短时间内找到直接答案、核心机制和边界。

其余缺口交给冷读器，不要让 Author 通过补字段或复制模板“修复”论文。
