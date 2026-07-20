---
name: mathmodel-review-r4-format-visual
description: 独立格式、视觉和提交包审核，检查 PDF 页面、字体、匿名、哈希和官方格式。
---

# R4 格式与视觉审核

先复验 request 强制绑定的 `FORMAT_AUDIT.json`，其机器硬失败不得被文字结论覆盖；再逐页渲染
最终 PDF 并检查 A4、2.5 cm 页边距、第一页摘要、页数、文件大小、公式和图表可读性。
每条 finding 必须声明 `change_level` 和 `affected_questions`。结论只能是 `COMPLIANT`、
`FIX_REQUIRED` 或 `NOT_COMPLIANT`。
