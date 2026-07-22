# 仓内数学建模知识

本目录保存由 `shumozizi` 自己生成和维护的结构化优秀论文知识，不依赖其他仓库生成知识包。

- `cards/papers/`：Markdown + YAML front matter 论文卡；
- `indexes/papers.json`：由论文卡生成的简单可解释索引；
- `training/pilot/`：首期材料清点和训练记录；
- `sources.example.json`：本机只读材料目录示例。

原始 PDF、DOCX、图片和真实路径配置不得提交。把本机路径写入未跟踪的
`knowledge/sources.local.json`，或设置环境变量：

```powershell
$env:SHUMO_EXCELLENT_PAPER_DIR="D:\path\to\excellent-paper-cache"
```

清点和建立索引：

```powershell
python scripts/knowledge/inventory_sources.py `
  --source-dir $env:SHUMO_EXCELLENT_PAPER_DIR `
  --output knowledge/training/pilot/source_inventory.json

python scripts/knowledge/build_index.py
```

论文卡必须同时记录可迁移模式、不可迁移内容、论文不足、缺失验证、复现风险和来源页码。
论文中的数字、结论和代码不得直接迁移到新题。

## Capability-First v3 按需参考

- `problem-decomposition.md`：拆解问题、共享对象与关键歧义；
- `model-selection-matrix.md`：按数学本质生成候选路线；
- `cookbooks/`：预测、优化、评价和机理问题的最小实践菜单；
- `model-validation.md`：按主张选择验证；
- `paper-writing/` 与 `figure-contract.md`：论文与图表叙事。

这些文件只提供候选与检查菜单。完整赛题当前阶段最多读取一到两个相关文件，不能全量加载，也不能代替当前题的 probe、baseline 或路线比较。
