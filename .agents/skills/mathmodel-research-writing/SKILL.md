---
name: mathmodel-research-writing
description: 使用仓内比赛模板撰写和编译数学建模竞赛论文。负责全文论证链：问题重述、模型选择理由、推导、结果解释、直接答案和限制。由 mathmodel-paper 调用，不负责计算或修改结果。
---

# 竞赛论文论证写作

本 Skill 负责把当前运行的真实模型、结果和图表组织成完整论证论文。它不搜索网络、不查找同题答案、不复制优秀论文内容，也不自行修改数值结果。

## 接收材料

- 原题
- 实际方法画像（`analysis/method_profile.json`）
- 高价值关键主张（`analysis/critical_claims.json`）
- 已通过科学审核且仍为 current 的结果与证据边界
- 当前论文级图表（`figures/publication/`）
- 学习模式（`knowledge/patterns/` 和 `knowledge/cards/papers/`）
- 比赛模板

## 写作流程

### 第一步：建立论证提纲

先生成 `paper/argument-outline.md`，每问回答：

1. 题目要求什么
2. 核心难点是什么
3. 为什么选择该模型
4. 还有什么备选路线
5. 关键数学关系是什么
6. 实际怎么求解
7. 结果是什么
8. 图表说明了什么
9. 结果为什么形成
10. 验证了什么
11. 还不能证明什么
12. 最终直接答案是什么

不要求固定表格式、字数或句数门槛。120 字符、3 个句子、技术内容和解释词只能作为机械层的最低非空壳信号，不能据此声称模型合理、推导正确或论证质量已获确认。

### 第二步：选择模板

在 `visualization -> paper` 前调用受控选择器：

```powershell
python scripts/paper/select_template.py runs/<run-id> \
  --language <zh|en> --engine auto \
  --reason "比赛、语言与仓内模板匹配；优先 LaTeX。" --materialize
```

### 第三步：写作正文

保留但不硬性要求以下论证角色（可合并章节标题）：

- 摘要
- 问题重述
- 问题分析
- 假设与符号
- 统一模型
- 逐问模型与求解
- 验证与误差
- 模型评价
- 结论
- 源码附录

每个问题至少包含：题意解释 / 模型选择理由 / 变量与公式 / 实际求解过程 / 结果 / 验证 / 限制 / 直接答案。

### 第四步：源码附录

根据赛事规则决定：

- **赛事允许且页数不受影响**：完整相关源码进入 PDF 附录
- **赛事限制页数**：PDF 放关键代码和文件清单（文件名 / 功能 / 哈希），完整源码放 `paper/submission/source/`

至少收录赛事要求的主求解入口、核心模型、scorer、独立验证、关键绘图脚本和运行说明；PDF 与附件的分配以赛事规则为准，不强制某一引擎或把全部工程塞入 PDF。

### 第五步：学习应用记录

写入 `paper/learning-application.md`，只写：

- 参考了什么模式
- 实际应用在哪一项实验/图/章节
- 没有迁移什么内容（原论文公式、数值、代码）

## 引用与编译

只引用实际采用的方法、定义或数据来源。完成后由 mathmodel-paper 编译：

```powershell
python scripts/paper/compile_paper.py runs/<run-id>
```

编译前 `check_paper_readiness.py` 重新计算 argument map v3 对 `method_profile`、`critical_claims`、逐问 objective semantics、当前结果和当前 publication figures 的全部哈希绑定。机械结构信号只检查缺问、空章节、直接答案和最低非空壳信号；真正的模型合理性、推导有效性、结果解释和论文说服力只由独立 PDF 盲审裁决。
