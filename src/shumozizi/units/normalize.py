"""将论文中的中英文和 LaTeX 单位写法归一化为 Pint Quantity。"""

from __future__ import annotations

import re

import pint

from shumozizi.units.registry import chinese_aliases, unit_registry

_LATEX_SPACING = re.compile(r"\\[,;:! ]")
_LATEX_WRAPPER = re.compile(r"\\(?:mathrm|textrm|text)\s*\{([^{}]+)\}")
_LATEX_POWER = re.compile(r"\^\s*\{?\s*([+-]?\d+)\s*\}?")

_DIRECT_ALIASES = {
    "%": "percent", "％": "percent", r"\%": "percent",
    "μm": "micrometer", "µm": "micrometer", "um": "micrometer",
    "nm": "nanometer", "mm": "millimeter", "cm": "centimeter", "dm": "decimeter",
    "km": "kilometer", "m": "meter", "s": "second", "min": "minute", "h": "hour",
    "kg": "kilogram", "t": "metric_ton", "Pa": "pascal", "MPa": "megapascal",
    "°C": "degC", "℃": "degC", "K": "kelvin", "km/h": "kilometer / hour",
    "m/s": "meter / second",
}


def normalize_unit(unit: str | None) -> str | None:
    """归一化正文单位字面量为 Pint 能解析的表达式。

    Args:
        unit: 紧邻数值的原始单位文本。

    Returns:
        可交给 Pint 的单位表达式；空单位返回 ``None``。
    """
    if unit is None:
        return None
    value = unit.strip()
    if not value:
        return None
    value = _LATEX_SPACING.sub("", value)
    value = value.replace(r"\upmu", "µ").replace(r"\mu", "µ")
    value = _LATEX_WRAPPER.sub(r"\1", value)
    value = _LATEX_POWER.sub(r"**\1", value)
    value = value.replace("·", "*").replace("×", "*")
    if value in chinese_aliases():
        return chinese_aliases()[value]
    if value in _DIRECT_ALIASES:
        return _DIRECT_ALIASES[value]
    return value


def compatible_units(left: str | None, right: str | None) -> bool:
    """判断两个显式单位是否同量纲。"""
    if left is None or right is None:
        return left is right
    registry = unit_registry()
    try:
        return registry.Quantity(1, normalize_unit(left)).dimensionality == registry.Quantity(
            1, normalize_unit(right)
        ).dimensionality
    except (pint.DimensionalityError, pint.UndefinedUnitError):
        return False


def quantity_in_unit(value: float, source_unit: str | None, target_unit: str | None) -> float | None:
    """把数值从源单位换算到目标单位；单位不兼容时返回 ``None``。"""
    if source_unit is None and target_unit is None:
        return value
    if source_unit is None or target_unit is None:
        return None
    registry = unit_registry()
    try:
        return float(registry.Quantity(value, normalize_unit(source_unit)).to(normalize_unit(target_unit)).magnitude)
    except (pint.DimensionalityError, pint.UndefinedUnitError):
        return None
