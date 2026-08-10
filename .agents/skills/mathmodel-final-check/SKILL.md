---
name: mathmodel-final-check
description: 对 Competition-First v3.1 已编译论文执行机械 QA、当前事实复验和提交检查；不承担 final audit 或独立科学判断。
---

# 机械终检

在 `verify` 阶段运行：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

它检查 PDF 可读性、匿名、占位符、乱码、裁切、空白页、当前结果与图表哈希、指标引用、数字一致性、模板和编译回执；可用时会用 PyMuPDF 与 Poppler 对全部页面做双渲染复验，并检查可抽取页脚中的页码连续性。通过只表示提交物和当前事实没有机械漂移，不证明数学正确性、最优性、论文说服力或两个 renderer 的逐像素一致。

对已知风险页（例如发现过页码前导数字、表格分页或图形裁切异常的页），先导出并人工看图：

```powershell
python tools/qa/pdf_qa.py runs/<run-id>/paper/final.pdf --critical-page 15 --critical-page 17 --critical-page-output-dir runs/<run-id>/paper/qa-critical-pages
```

确认 PNG 中的页码、图注、表格、字体和裁切后，才可以追加 `--manual-critical-review-confirmed` 记录人工复核。页脚文本检查和双渲染不能替代这一步；未指定关键页时，报告会明确保留此能力边界。

CUMCM v3.2 在机械 QA 通过后，用 `python scripts/paper/cumcm_adapter.py <run_dir> finalize --input <json>` 在既有 `paper/CUMCM_LAYOUT_AUDIT.json` 中补正文页数、图中文字、浮动体断句、公式溢出、跨章一致性、符号定义和 Word/PDF 检查。页面节奏探针只提供高文字密度、首个视觉锚点和图表后置告警；不得据此强制图数或页数。闭合后 `layout_audited_revision` 必须等于当前 `paper_render_revision`，重新编译即失效。页数区间只触发说明或复核；发现论证发育不足或未解决版面问题才返工。不要新增第三份 CUMCM 审核文件。

PDF 盲评仍需存在或显式记录跳过原因；P0/P1、已验证反例、独立复算冲突、不可行和性质测试失败仍然阻断。不得创建 `final_review`、final-audit packet 或第三轮终审。
