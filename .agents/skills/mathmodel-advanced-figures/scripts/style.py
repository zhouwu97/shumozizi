"""竞赛论文统一视觉样式（借鉴 MathModel 的全局样式基线，不复制其数据/结论）。

全篇所有正式图复用同一套 seaborn 主题、调色板、字体与 DPI，保证"风格统一、
高级、清晰"。颜色语义与 model-native renderer 对齐：正式答案深青、阈值金色、
敏感性灰、不可行暖红、网络骨架蓝。

用法：``from style import apply_competition_style`` 后直接绘图。
"""
from __future__ import annotations

import matplotlib as mpl
import seaborn as sns

# 与 figures/renderers.py 一致的语义色，保证新旧图全篇同语义。
TEAL = "#147D80"      # 正式答案
GREEN = "#2E7D32"     # 正式答案备用
CORAL = "#D95D4F"     # 不可行/失败
GOLD = "#D6A420"      # 阈值与活跃边界
BLUE = "#3E6FB0"      # 网络/骨架等高对比对象
GRAY = "#7A8793"      # 敏感性/域外
LIGHT = "#E7ECEF"     # 背景浅色
PALE_GOLD = "#F5E3B3" # 阈值带浅色

CJK_FONTS = ("SimSun", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial")


def apply_competition_style(rc_text_size: int = 11) -> None:
    """设置全篇统一样式：seaborn 主题 + 语义调色板 + 中文字体 + DPI>=300。

    Args:
        rc_text_size: 正文源字号。按 0.85--0.98 页宽缩放后仍应不低于 8pt。
    """
    sns.set_theme(style="whitegrid", palette="deep")
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": list(CJK_FONTS),
            "axes.unicode_minus": False,
            "font.size": rc_text_size,
            "axes.labelsize": rc_text_size + 1,
            "axes.titlesize": rc_text_size + 2,
            "xtick.labelsize": rc_text_size - 1,
            "ytick.labelsize": rc_text_size - 1,
            "legend.fontsize": rc_text_size - 1,
            "axes.linewidth": 0.9,
            "savefig.facecolor": "white",
            "savefig.dpi": 300,
            "pdf.fonttype": 42,
            "axes.grid": True,
            "grid.color": LIGHT,
            "grid.linewidth": 0.7,
            "figure.autolayout": True,
        }
    )


def clean_axes(ax) -> None:
    """去掉上/右边框，保留网格（seaborn whitegrid 之上的微调）。"""
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


__all__ = [
    "TEAL", "GREEN", "CORAL", "GOLD", "BLUE", "GRAY", "LIGHT", "PALE_GOLD",
    "apply_competition_style", "clean_axes",
]
