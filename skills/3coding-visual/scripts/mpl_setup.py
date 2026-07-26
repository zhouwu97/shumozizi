"""matplotlib 中文字体强制引导模块（数学建模数据图统一入口）。

为什么需要它：`3coding-visual` 阶段生成的每一张数据图都会进入中文论文正文，
若使用 matplotlib 默认的 DejaVu Sans，坐标轴/图例/标题会是英文，且中文字符
显示为豆腐块（□）。这类"半成品图"是国奖评审的硬伤。本模块把中文字体注册、
负号修正、矢量文本嵌入等易错设置收敛到一处，任何作图脚本只需：

    from mpl_setup import apply_chinese_style
    apply_chinese_style()          # 之后照常 plt.plot / plt.xlabel("波数") ...

设计要点（WHY）：
  1. 跨平台候选字体列表：Windows(SimHei/微软雅黑)、macOS(Songti/Heiti)、
     Linux(Noto/文泉驿)。按可用性择优，而非写死单一字体。
  2. 找不到任何中文字体时**直接抛错**，让作图阶段"响亮地失败"，而不是静默
     产出英文/豆腐块图，等到验收阶段才被发现。
  3. `pdf.fonttype=42`/`ps.fonttype=42`：把文字以 TrueType 形式嵌入 PDF，
     保证标签可被 pdftotext 提取——这既让图中文字可复制，也让 6verity 的
     "图内中文标签"门禁能真正校验到 CJK 字符。
  4. `axes.unicode_minus=False`：避免负号渲染成缺字方块。
"""

from __future__ import annotations

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

# 中文黑体族优先级：Windows -> macOS -> Linux 常见 CJK 字体。
_CJK_SANS_CANDIDATES = [
    "SimHei",              # Windows 黑体
    "Microsoft YaHei",     # Windows 微软雅黑
    "Heiti SC",            # macOS 黑体
    "Songti SC",           # macOS 宋体（sans 退化用）
    "PingFang SC",         # macOS 苹方
    "Noto Sans CJK SC",    # Linux/跨平台 思源黑体
    "Source Han Sans SC",  # 思源黑体（同族别名）
    "WenQuanYi Zen Hei",   # Linux 文泉驿正黑
    "WenQuanYi Micro Hei",
    "SimSun",              # 兜底：Windows 宋体
    "STSong",              # 兜底：macOS 华文宋体
]


def available_cjk_fonts() -> list[str]:
    """返回当前 matplotlib 能识别的中文候选字体（按优先级）。"""
    installed = {f.name for f in fm.fontManager.ttflist}
    return [name for name in _CJK_SANS_CANDIDATES if name in installed]


def apply_chinese_style(lang: str = "zh", extra_rc: dict | None = None) -> str:
    """应用统一的中文论文作图样式。

    Args:
        lang: "zh" 强制中文字体（找不到即抛错）；"en" 时仅做通用美化，
            沿用默认西文字体，不强制 CJK。
        extra_rc: 需要覆盖的额外 rcParams。

    Returns:
        实际选用的主字体名（英文论文返回默认 sans 名）。

    Raises:
        RuntimeError: lang="zh" 但系统未安装任何可用中文字体。
    """
    # 通用矢量/排版设置（中英论文都适用）。
    matplotlib.rcParams.update(
        {
            "pdf.fonttype": 42,      # TrueType，文字可提取、可编辑
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "axes.unicode_minus": False,
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "legend.fontsize": 10,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "grid.linewidth": 0.6,
        }
    )

    chosen = matplotlib.rcParams.get("font.sans-serif", ["DejaVu Sans"])[0]

    if lang == "zh":
        fonts = available_cjk_fonts()
        if not fonts:
            raise RuntimeError(
                "未找到任何可用的中文字体，无法生成中文标签图表。\n"
                "请安装以下任一字体后重试：SimHei / 微软雅黑 / 思源黑体(Noto Sans CJK) / 文泉驿正黑。\n"
                "  - Windows：系统自带 SimHei，通常无需安装。\n"
                "  - macOS：系统自带 Heiti SC / Songti SC。\n"
                "  - Linux(Debian/Ubuntu)：sudo apt-get install fonts-noto-cjk fonts-wqy-zenhei\n"
                "严禁退化为 DejaVu Sans 输出英文/豆腐块图。"
            )
        # 把中文字体放在 sans-serif 族最前，DejaVu 兜底西文字符。
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = fonts + ["DejaVu Sans"]
        chosen = fonts[0]

    if extra_rc:
        matplotlib.rcParams.update(extra_rc)

    return chosen


def assert_cjk_ready() -> None:
    """作图前的一行断言：确认中文字体已就绪，否则抛错。"""
    if not available_cjk_fonts():
        raise RuntimeError(
            "中文字体未就绪：available_cjk_fonts() 为空。请先安装中文字体再作图。"
        )


if __name__ == "__main__":
    # 自检：打印可用字体并生成一张中文样例图，肉眼确认无豆腐块。
    fonts = available_cjk_fonts()
    print("可用中文字体：", fonts or "（无！）")
    name = apply_chinese_style("zh")
    print("选用主字体：", name)
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.plot([1, 2, 3], [-1, 0, 2], marker="o", label="示例曲线")
    ax.set_title("中文字体自检：波数-反射率")
    ax.set_xlabel("波数 (cm$^{-1}$)")
    ax.set_ylabel("反射率 (%)")
    ax.legend()
    out = "mpl_setup_selfcheck.pdf"
    fig.savefig(out)
    print("已输出自检图：", out, "（打开确认中文与负号正常）")
