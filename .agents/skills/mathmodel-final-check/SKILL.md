---
name: mathmodel-final-check
description: 对 Competition-First v3.1 已编译论文执行机械 QA、当前事实复验和提交检查；不承担 final audit 或独立科学判断。
---

# 机械终检

在 `verify` 阶段运行：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

它检查 PDF 可读性、匿名、占位符、乱码、裁切、空白页、当前结果与图表哈希、指标引用、数字一致性、模板和编译回执。通过只表示提交物和当前事实没有机械漂移，不证明数学正确性、最优性或论文说服力。

PDF 盲评仍需存在或显式记录跳过原因；P0/P1、已验证反例、独立复算冲突、不可行和性质测试失败仍然阻断。不得创建 `final_review`、final-audit packet 或第三轮终审。
