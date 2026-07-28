# CUMCM-main 2023 B 学习审计

## 目的与身份边界

这是对用户提供的 `CUMCM-main` 本地工作区的离线结构学习，不是对其获奖身份、数学结论或工程完成度的认证。题面与最终论文均可在来源文件中核对，但仓库未提供可核验的奖项证明，也没有发现仓库根目录统一许可证；因此不复制原文、数字、代码或图表，只提取论证结构和失败模式。

## 已核对来源

- 原题：`CUMCM-main/workspaces/B题/problem/B题.pdf`，3 页，SHA-256 `E709E066139EA0A4BB64AA7E56EA097725A1F2B4E5161FC8C7E50C48BE079396`。
- 最终 PDF：`CUMCM-main/workspaces/B题/validation/main.pdf`，14 页，SHA-256 `FD1655D9AEFD54D3F732EF5BE00D48C4DB5A1F23486E0516BFA513AE7699A29B`。
- 论文蓝图：`CUMCM-main/workspaces/B题/reports/paper-blueprint.md`，SHA-256 `3435A11B2203D11CB5BD4A304196093DB916C4F1EF96C38C2BA41F6B0E3B57A9`。
- 论文评阅：`CUMCM-main/workspaces/B题/reports/paper-review.md`，SHA-256 `8B83BFC74DF589B781DAF347A10B6334E588E3C88BF594A093EC52CD2912496C`。
- 任务状态：`CUMCM-main/workspaces/B题/todo.md`，SHA-256 `20076C77A18738821E2D745909F28BCC9921E83E833A54FAF4814EF90C2DC2D5`。

## 值得迁移的结构

1. 先写共享数学对象，再按“继承对象 -> 新增困难 -> 新机制 -> 结果增量”组织各问；这能把逐问答案变成一个研究故事。
2. 分开模型和算法：先说明几何、状态、约束或统计对象，再说明算法为何匹配非凸、整数、昂贵评价或噪声等困难。
3. 图表按论证任务登记，正文在图前提出问题、图后给出观察和决策后果。
4. 结果段落使用“结果 -> 含义 -> 误差/约束 -> 独立验证 -> 适用边界”闭环。

## 必须反向吸收的缺陷

- `todo.md` 同时把 implementation 和 verification 标成 skipped，而 `paper-review.md` 又宣称所有硬问题关闭；上层论文状态不能覆盖底层生产证据缺失。
- 五份 `paper/drafts/round-*.docx` 的 SHA-256 完全相同；轮次名称不能替代内容增量检查。
- 最终论文明确承认没有全局最优下界，只能称“预算内最好可行解”；类似措辞应保留在当前项目的证据边界中。

## 对当前项目的实际改动

当前项目没有新增固定五轮状态机，而是在作者侧 `PAPER_BLUEPRINT.md` 中加入可往返的内容成熟度动作，并为每个问题输出继承来源、继承对象、新增困难、新增机制、原模型不足和答案增量字段。字段是写作规划，不是生产结果或论文事实来源。

