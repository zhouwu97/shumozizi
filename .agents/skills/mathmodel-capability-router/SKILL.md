---
name: mathmodel-capability-router
description: 为 Capability-First v3 数学建模赛题选择并冻结求解、交叉、独立验证和本地工具能力。仅在分析完成、实验开始前的 capability_route 阶段使用；用于几何、优化、机理、网络、预测或评价题的能力组合，不生成题目答案或论文。
---

# 建模能力路由

能力路由只记录当前题的执行决定，不决定答案，也不要求为了满足标签而增加模型、工具或图表。

1. 读取题面、分析报告、状态和决策。只使用本地知识库，不联网查同题答案。
2. 选择实际题型与少量能力，分别说明它们处理的当前风险。读取 `references/skill-routing.yaml` 并调用匹配的主动 Skill：几何/运动题调用 `$mathmodel-geometry-oracle`，空间结构影响结论时再调用 `$mathmodel-geometry-visual`；优化题调用 `$mathmodel-optimizer-benchmark`。MATLAB 烟雾测试通过时，高风险几何或独立优化挑战还要调用 `$mathmodel-matlab` 形成不同工具链的数值 oracle。几何、运动或机理题必须选择真正独立的 oracle：不同推导优先，不得把同一领域判定函数换采样密度当独立验证。
3. 探测本机工具：

   ```powershell
   python scripts/capabilities/detect_tools.py runs/<run-id>
   ```

   Python 可作生产引擎；MATLAB/Octave 仅在实际烟雾测试、所需函数或许可证均成功后选择。优化题不因路由而强制使用它们。
4. 选择至多五项与当前路线相关的本地知识资产。主对话只写题型、能力、独立验证、工具与资产路径；运行时补齐时间、哈希、工具收据和文件摘要。例如：

   ```json
   {
     "schema_version": "1.2",
     "problem_families": ["geometry_kinematics", "optimization"],
     "capabilities": [
       {"id": "geometry-kinematics", "reason": "有限视线和连续目标决定可行性。"},
       {"id": "nonsmooth-optimization", "reason": "事件边界使目标不光滑。"}
     ],
     "verification_capability": {"id": "independent-segment-oracle", "reason": "以不同推导复算临界几何。"},
     "toolchain": {"production_engine": "python", "independence_strategy": "alternative_formulation"},
     "visual_evidence": {"spatial_structure_affects_conclusion": true},
     "knowledge_assets": ["knowledge/cards/structural-preflight.json"]
   }
   ```

5. 登记路由后立即实际读取已选资产并冻结最小消费收据：

   ```powershell
   python scripts/capabilities/record_route.py runs/<run-id> --input code/capability-route.json
   python scripts/capabilities/record_knowledge_consumption.py runs/<run-id>
   ```

   之后进入实验。按路由表调用的 Skill 必须落实到当前题的代码、测试或图表合同中；只把 Skill 名写进 JSON 不算调用成功。读取收据证明资产和路线没有漂移，不把文件读取误称为数学结论。
