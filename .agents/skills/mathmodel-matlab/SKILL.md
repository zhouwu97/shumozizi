---
name: mathmodel-matlab
description: 在 Capability-First v3 中使用本机 MATLAB 或 GNU Octave 提供可复现的独立实现能力。仅在能力路由实际选择该引擎时使用；不把 MATLAB 本身当作独立性、proxy-exact 风险或科学正确性的证明。
---

# MATLAB / Octave 独立实现能力

MATLAB/Octave 只是可选 engine。独立性来自不同推导、参数化、算法族或判定实现，而不是文件扩展名或工具品牌；第二套 Python、Julia、R、反例搜索和性质测试也可承担同一验证职责。

1. 先读取 `state/capability-route.json` 与 `state/tooling.json`。仅运行路由选择且探测为可用的引擎；否则记录不可用并改用路由允许的替代公式 oracle，不能安装后假设其结果与生产环境等价。
2. 使用 `code/matlab/` 保存 `.m` 脚本，输入只从 `problem/`、受控参数文件或当前结果读取；数值证据输出写入 `results/evidence/`，证据图写入 `figures/evidence/`。在脚本头部记录输入路径、单位和运行命令。作为路由指定的独立 oracle 时，必须通过 v3 执行器以 `kind=independent-oracle` 登记，并显式把该 `.m` 文件列为输入。
3. 作为独立 oracle 时，不导入、翻译或调用 Python 的核心判定函数。几何题可用“线段参数代入球面二次方程”对照 Python 的投影裁剪；机理题可用不同积分器/步长与守恒残差；优化题使用不同的搜索族或参数化。共享题意是允许的，共享判定语义和源码不是。
4. MATLAB 可优先用 `plot3`、`surf`、`cylinder`、`sphere` 构建三维对象和边界；优化工具箱的 `ga`、`particleswarm`、`patternsearch`、`surrogateopt` 只有在许可证和工具箱真实存在时才用。Octave 不应声称支持 MATLAB 专有工具箱。
5. `method_profile.stochastic=true` 才要求 multiseed；`uses_proxy_objective=true` 才要求 proxy-exact。MATLAB/Octave 的存在不得触发其中任一风险。独立实现、反例、性质测试或更优候选产生负面证据时，统一交给 `independent_evidence_consequence`，先级联失效相关结果、图、argument map、论文与审核，再检查 verdict。

Windows 示例：

```powershell
matlab -batch "run('code/matlab/geometry_oracle.m')"
octave --quiet --no-gui code/matlab/geometry_oracle.m
```

若引擎不存在，停止该路线并在 `DECISIONS.md` 记录可用替代实现与其独立性边界；不要静默降为复用 Python 的同源 oracle。
