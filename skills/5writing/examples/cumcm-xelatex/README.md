# CUMCM XeLaTeX 模板 —— 演示样例

本目录是 `skills/5writing/templates/zh/cumcm-latex/`（正式模板）的**可编译演示**，
**不随模板实例化进入任何 run**（放在 `templates/` 之外，模板复制时不会带上它）。

## 用途

1. 演示模板排版效果：公式与交叉引用、三线表、跨页长表、示意图（TikZ 自绘）、
   代码清单、参考文献、附录。
2. 作为回归样例，验证模板 preamble 在本机 XeLaTeX 下确实编译通过。

## 编译

```bash
cd skills/5writing/examples/cumcm-xelatex
xelatex -interaction=nonstopmode main_demo.tex
xelatex -interaction=nonstopmode main_demo.tex   # 交叉引用需两遍
```

## 与正式模板的关系

- `main_demo.tex` 的 preamble 与模板 `main.tex` 保持一致，仅额外加载 `tikz`
  用于自绘演示图（避免演示依赖外部图片）。**修改模板 preamble 时请同步本文件。**
- 正式模板 `main.tex` 缺少正文 `sections/questions.tex` 时会 `\PackageError`
  明确报错，因此模板本身不单独编译；本演示提供了 `sections/questions.tex`
  等文件，故可独立编译。

## 验证要点

- 「参考文献」标题只出现一次（由 `thebibliography` 生成；`\referencescn`
  不再手写标题）。把 `main_demo.tex` 配置块中的 `\numberedreferencesfalse`
  改成 `\numberedreferencestrue`，标题会变为带编号的「六、参考文献」，且仍只有一处。
- 附录标题为「附录 A　核心代码」；将 `\showappendixtrue` 改为 `\showappendixfalse`
  可整节隐藏，且不产生空白页。
