---
name: mathmodel-capability-router
description: 旧 Capability-First v3.0 运行的兼容能力路由；v3.1 仅在分析或实验需要工具探测时按需使用。
---

# 兼容能力路由

Competition-First v3.1 没有 `capability_route` 阶段，也不把能力清单、知识消费收据或工具探测当作实验门禁。新运行在分析或实验中按需选择能提高当前路线或独立验证质量的工具。

仅在以下情况使用本 Skill：旧 v3.0 运行需要查看历史路由；当前题确实需要检测 MATLAB/Octave、选择几何 oracle 或公平优化基准；或一个独立工具能低成本推翻/支持当前结论。记录选择理由和实际使用，不为填字段调用能力。

它不得生成 `capability_route` 状态、阻断 `analysis -> experiment`，或要求方法画像、图表合同和固定知识资产。
