"""按竞赛解析论文交付格式要求。

Competition-First v3.1/v3.2 运行只保存自由竞赛字符串（``state["competition"]``），
不创建 Capability-First 的 Profile 锁。本模块把该字符串映射到已有比赛 Profile，
读取其 ``delivery`` 块，得到每种论文格式（PDF/Word）是否必交。这样 DOCX 不再被
硬编码为全局强制项：缺少 pandoc 的环境仍可提交纯 PDF，除非某竞赛显式声明必须
同时提交 Word。
"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import load_json
from shumozizi.core.repo_root import resolve_repo_root

# 竞赛自由字符串 → Profile ID。只映射拥有专属 Profile 的比赛；其余回退 generic。
# 采用子串匹配、长标记优先，避免短别名误吞长名称。
_PROFILE_ALIASES = {
    "全国大学生数学建模": "cumcm",
    "cumcm": "cumcm",
    "国赛": "cumcm",
    "national": "cumcm",
    "美国大学生数学建模": "mcm",
    "comap": "mcm",
    "icm": "mcm",
    "mcm": "mcm",
    "电工杯": "diangong",
    "diangong": "diangong",
}

# Profile 未声明 delivery 时的保守默认：PDF 必交、Word 可选。
_DEFAULT_DELIVERY: dict[str, bool] = {"pdf_required": True, "docx_required": False}


def _profile_id_for_competition(competition: str) -> str:
    """把自由竞赛字符串解析为 Profile ID。

    Args:
        competition: ``state["competition"]`` 中的自由文本。

    Returns:
        匹配到的 Profile ID；无法识别时回退 ``generic``。
    """
    normalized = competition.strip().casefold()
    for marker, profile_id in sorted(
        _PROFILE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if marker in normalized:
            return profile_id
    return "generic"


def delivery_requirements_for_competition(competition: str) -> dict[str, bool]:
    """解析某竞赛必须提交的论文格式。

    Args:
        competition: 自由竞赛字符串，可为空。

    Returns:
        ``{"pdf_required": bool, "docx_required": bool}``。未识别竞赛或 Profile
        未声明 ``delivery`` 时，回退到 PDF 必交、Word 可选的保守默认，避免因缺少
        pandoc 而阻断纯 PDF 提交。
    """
    profile_id = _profile_id_for_competition(competition)
    profile_path = resolve_repo_root(Path(__file__)) / "profiles" / f"{profile_id}.json"
    if not profile_path.is_file():
        return dict(_DEFAULT_DELIVERY)
    profile = load_json(profile_path)
    delivery = profile.get("delivery")
    if not isinstance(delivery, dict):
        return dict(_DEFAULT_DELIVERY)
    return {
        "pdf_required": bool(delivery.get("pdf_required", True)),
        "docx_required": bool(delivery.get("docx_required", False)),
    }
