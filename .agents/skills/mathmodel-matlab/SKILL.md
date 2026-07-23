---
name: mathmodel-matlab
description: 在 Capability-First v3 中使用本机 MATLAB 或 GNU Octave 编写可复现的独立数值 oracle、优化挑战和三维科学图。仅在能力路由选择 matlab/octave 或需要独立实现时使用；不把未安装工具、同源公式或演示图称为独立验证。
---

# MATLAB / Octave 独立能力

Python 仍可作为生产求解器。MATLAB/Octave 的价值是以不同语言、公式推导或优化实现挑战高风险模型，并输出空间和曲面图；它不是整题重写或质量审批。

1. 先读取 `state/capability-route.json` 与 `state/tooling.json`。仅运行路由选择且探测为可用的引擎；否则记录不可用并改用路由允许的替代公式 oracle，不能安装后假设其结果与生产环境等价。
2. 使用 `code/matlab/` 保存 `.m` 脚本，输入只从 `problem/`、受控参数文件或当前结果读取；输出写入 `results/raw/` 或 `figures/`。在脚本头部记录输入路径、单位和运行命令。作为路由指定的独立 oracle 时，必须通过 v3 执行器以 `kind=independent-oracle` 登记，并显式把该 `.m` 文件列为输入；只有这样才能解锁科学红队。
3. 作为独立 oracle 时，不导入、翻译或调用 Python 的核心判定函数。几何题可用“线段参数代入球面二次方程”对照 Python 的投影裁剪；机理题可用不同积分器/步长与守恒残差；优化题使用不同的搜索族或参数化。共享题意是允许的，共享判定语义和源码不是。
4. MATLAB 可优先用 `plot3`、`surf`、`cylinder`、`sphere` 构建三维对象和边界；优化工具箱的 `ga`、`particleswarm`、`patternsearch`、`surrogateopt` 只有在许可证和工具箱真实存在时才用。Octave 不应声称支持 MATLAB 专有工具箱。
5. 导出论文图时生成 PNG、PDF/SVG 中可用格式并保留 `.m` 源；图中标注坐标轴、单位、图例和对象含义。脚本正常退出只说明运行成功，数值仍须通过题目特定验证与科学红队。

Windows 示例：

```powershell
matlab -batch "run('code/matlab/geometry_oracle.m')"
octave --quiet --no-gui code/matlab/geometry_oracle.m
```

若引擎不存在，停止该路线并在 `DECISIONS.md` 记录可用替代实现与其独立性边界；不要静默降为复用 Python 的同源 oracle。
