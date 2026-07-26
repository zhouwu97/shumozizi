"""matplotlib 中文字体强制引导模块（数学建模数据图统一入口）。

为什么需要它：`3coding-visual` 阶段生成的每一张数据图都会进入中文论文正文，
若使用 matplotlib 默认的 DejaVu Sans，坐标轴/图例/标题会是英文，且中文字符
显示为豆腐块（□）。这类"半成品图"是国奖评审的硬伤。本模块把中文字体注册、
负号修正、矢量文本嵌入等易错设置收敛到一处，任何作图脚本只需：

    from mpl_setup import apply_chinese_style
    apply_chinese_style()               # 折线图／柱状图（默认 profile="line"）
    apply_chinese_style(profile="heatmap")    # 热力图
    apply_chinese_style(profile="geometry3d") # 三维几何图

设计要点（WHY）：
  1. 跨平台候选字体列表：Windows(SimHei/微软雅黑)、macOS(Songti/Heiti)、
     Linux(Noto/文泉驿)。按可用性择优，而非写死单一字体。
  2. 找不到任何中文字体时**直接抛错**，让作图阶段"响亮地失败"，而不是静默
     产出英文/豆腐块图，等到验收阶段才被发现。
  3. `pdf.fonttype=42`/`ps.fonttype=42`：把文字以 TrueType 形式嵌入 PDF，
     保证标签可被 pdftotext 提取——这既让图中文字可复制，也让 6verity 的
     "图内中文标签"门禁能真正校验到 CJK 字符。
  4. `axes.unicode_minus=False`：避免负号渲染成缺字方块。
  5. profile 机制：字体嵌入与负号修复是硬配置，对所有图类型都必须；网格、
     字号等"风格"参数随图类型而异，通过 profile 控制，避免热力图/图像/
     三维图被折线图网格污染。
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

# ── 硬配置：无论何种图类型都必须应用 ────────────────────────────────────────
# 字体嵌入与负号修复属于"正确性"设置，不应因图类型而变化。
_HARD_RC: dict[str, object] = {
    "pdf.fonttype": 42,      # TrueType 嵌入：文字可提取、可编辑
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "axes.unicode_minus": False,  # 负号不渲染为方块
    "savefig.dpi": 300,           # 交付质量
    "savefig.bbox": "tight",
}

# ── Profile：只控制风格参数 ───────────────────────────────────────────────
# 折线图的网格对热力图是噪声；三维图有自己的平面网格；极坐标/网络图本无坐标含义。
# 各 profile 仅声明需要覆盖默认值的键，其余沿用 matplotlib 初始值。
_PROFILE_RC: dict[str, dict[str, object]] = {
    # 折线图 / 柱状图 / 散点图：轻度网格辅助读数。
    "line": {
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.6,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
    # 热力图（imshow / seaborn heatmap）：网格线会切割色块，必须关闭。
    "heatmap": {
        "axes.grid": False,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
    # 原始图像显示：无坐标语义，网格无意义。
    "image": {
        "axes.grid": False,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
    # 三维几何图（Axes3D surface/scatter）：Axes3D 有内置平面网格，
    # rcParams 的 axes.grid 对其无效，但显式关闭可避免 2-D 子图污染。
    "geometry3d": {
        "axes.grid": False,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
    # 雷达图（polar axes）：极坐标自管网格，rcParams 网格会产生矩形干扰。
    "radar": {
        "axes.grid": False,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
    # 网络图（networkx）：无坐标轴语义，网格无意义，通常也会 ax.axis('off')。
    "network": {
        "axes.grid": False,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
    # 示意图 / 技术路线图（drawio 导出或 matplotlib patch 绘制）：纯示意，无刻度。
    "schematic": {
        "axes.grid": False,
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
    },
}

# profile 的公开名称集合，用于参数校验。
PROFILES: frozenset[str] = frozenset(_PROFILE_RC)


def available_cjk_fonts() -> list[str]:
    """返回当前 matplotlib 能识别的中文候选字体（按优先级）。"""
    installed = {f.name for f in fm.fontManager.ttflist}
    return [name for name in _CJK_SANS_CANDIDATES if name in installed]


def apply_chinese_style(
    lang: str = "zh",
    *,
    profile: str = "line",
    extra_rc: dict | None = None,
) -> str:
    """应用统一的中文论文作图样式。

    字体嵌入（pdf.fonttype）、负号修复（unicode_minus）等"正确性"设置始终生效；
    网格、字号等"风格"设置由 profile 决定，extra_rc 可进一步覆盖。

    Args:
        lang: "zh" 强制中文字体（找不到即抛错）；"en" 仅做通用美化。
        profile: 图类型预设，决定网格等风格参数。可选值：
            "line"       — 折线图／柱状图／散点图（默认，grid=True）
            "heatmap"    — 热力图（grid=False，避免切割色块）
            "image"      — 原始图像（grid=False）
            "geometry3d" — 三维几何图（grid=False，Axes3D 自管网格）
            "radar"      — 雷达图／极坐标（grid=False，polar 自管）
            "network"    — 网络图（grid=False，ax.axis("off") 配合使用）
            "schematic"  — 示意图／技术路线图（grid=False）
        extra_rc: 需要最终覆盖的额外 rcParams，优先级最高。

    Returns:
        实际选用的主字体名（英文论文返回默认 sans 名）。

    Raises:
        ValueError: profile 不在已知列表中。
        RuntimeError: lang="zh" 但系统未安装任何可用中文字体。
    """
    if profile not in PROFILES:
        raise ValueError(
            f"未知 profile: {profile!r}。可用值：{sorted(PROFILES)}"
        )

    # 第一层：硬配置（正确性，不随图类型变化）。
    matplotlib.rcParams.update(_HARD_RC)

    # 第二层：profile 风格配置（网格、字号等）。
    matplotlib.rcParams.update(_PROFILE_RC[profile])

    chosen = matplotlib.rcParams.get("font.sans-serif", ["DejaVu Sans"])[0]

    # 第三层：中文字体注册（lang="zh" 时）。
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

    # 第四层：调用方覆盖（优先级最高）。
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
    # 自检：打印可用字体，并为每种 profile 各生成一张样例，肉眼确认无豆腐块。
    fonts = available_cjk_fonts()
    print("可用中文字体：", fonts or "（无！）")

    for _profile in sorted(PROFILES):
        name = apply_chinese_style("zh", profile=_profile)
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.plot([1, 2, 3], [-1, 0, 2], marker="o", label="示例曲线")
        ax.set_title(f"profile={_profile}  字体={name}")
        ax.set_xlabel("波数 (cm$^{-1}$)")
        ax.set_ylabel("反射率 (%)")
        ax.legend()
        out = f"mpl_setup_selfcheck_{_profile}.pdf"
        fig.savefig(out)
        plt.close(fig)
        print(f"  [{_profile}] axes.grid={matplotlib.rcParams['axes.grid']}  → {out}")
