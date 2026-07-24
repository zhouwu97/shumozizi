---
name: mathmodel-paper
description: 使用 Capability-First v3 中真实执行且仍有效的结果撰写、编译和局部修订数学建模论文；用于完整论文、章节补丁和图表叙事。
---

# 证据驱动的数学建模论文

论文的重点是题目的数学对象、推导、求解、结果解释与局限。内部流程名称、收据和质量协议不应出现在正文。

1. 只在 `paper` 阶段写正式稿。读取当前运行的建模报告、实验报告、决策、结果和图表；只写已通过科学审查、仍为当前生产结果的事实。运行时会复验来源链，作者不必在正文或主对话逐项抄录哈希、适配器或收据。
2. **实际调用已安装的 `$mathmodel-research-writing` 完成正文写作。** 先按该 Skill 建立 `paper/argument-outline.md`，再展开段落；不得由本 Skill 用标题、表格和结论句直接拼成论文。职责必须分开：写作 Skill 负责 argument outline、段落推进和“主张 → 证据 → 解释/机制 → 限制”链条；本 Skill 负责当前证据边界、argument map v3、图表引用、LaTeX 和编译。
3. 模板必须在从 `visualization` 进入 `paper` 前选择并实例化。默认使用 LaTeX：

   ```powershell
   python scripts/paper/select_template.py runs/<run-id> `
     --language zh --engine auto `
     --reason "比赛、语言与仓内模板匹配；优先 LaTeX。" --materialize
   ```

   `auto` 会优先 LaTeX；只有 LaTeX 环境不可用时才记录受控 Typst 回退。用户明确选择 Typst 才传 `--engine typst`。未知赛事会阻断，不得复制 `default` 或手工重建模板。
4. argument outline 必须逐问写出：采用的题意与目标、该模型相对备选路线的选择理由、变量/假设、核心证明义务、关键公式或推导、实际求解证据、结果含义、验证与限制、可定位的直接答案。每个实验簇都要有 takeaway，解释数值为什么支持当前主张以及不能推出什么；共享模型可以复用，但不能以总表、图注或前一问替代本问论证。
5. 正文按完整段落展开。每问至少形成“题意/主张 → 数学推导 → 定量或图表证据 → 结果解释 → 验证/限制”的闭环；禁止只有大标题、稀疏表格、几行口号式结论，禁止用重复的“效果良好、结果稳定”代替机制或比较。正文采用比赛模板的常规字号，不用放大字号填充页面。
6. 图表服务于论证：交代它回答的科学问题、数据/模型来源、它支持的结论和不能证明的内容。数字、图表和结论只能来自本次运行；离线论文卡只可改善表达和结构，不能提供事实、数值、代码或引用。新建 `evidence_map` 必须使用 2.1 精度策略，展示小数位由模型误差、离散化误差和独立复算差异中的综合上界决定，不能按求解器内部精度虚报位数。
7. 只有确有当前运行证据的题目特定结构、模型或算法改进才能称为创新。已有方法的组合、实现和常规图表应如实表述为方法组合或工程实现；需要深入创新证据时按需查阅 `docs/CODEX_WORKFLOW.md`。
8. 删除标题、摘要、关键词和参考文献样例。参考文献只列实际采用的方法或数据来源，不为凑数量引入条目。LaTeX 使用 `\cite{...}`，并在必要事实旁保留非渲染的结果标记；由最终检查复验。
9. 编译并冻结当前 PDF：

   ```powershell
   python scripts/paper/compile_paper.py runs/<run-id>
   ```

   源码策略必须服从赛事要求：PDF 放必要的关键代码与可核查说明；赛事要求完整工程时，把完整源码、环境与入口放入提交附件。独立验证可以使用任何真实登记的引擎、反例或性质测试，不强制 MATLAB，也不强制把完整工程文本塞入 PDF。

   生成 `paper/final.pdf` 后运行 `paper_structure_signal_report` 与 PDF 机械检查，新生产报告只写 `qa/paper-structure-signals.json`，状态为 `signals_present` 或 `missing_required_signals`。`mechanical_gate_passed=true` 仅表示逐问结构和最低非空壳信号存在，明确不评价数学正确性或论证质量，也不能绕过独立 PDF 盲审。进入 `paper_review` 后先由全新对话输出开放盲审报告，再由独立 coverage task 从当前 critical claims、argument map、publication figures 和赛事规则派生风险并查漏；additional findings 的 P0/P1 或任意 `disposition=blocking` 必须阻断。修改论文、图表或 PDF 后必须重新编译、重新盲审、动态查漏和机械终检。
