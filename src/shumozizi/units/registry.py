"""构造可复用的 Pint 单位注册表，并加载仓内中文别名。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pint


@lru_cache(maxsize=1)
def unit_registry() -> pint.UnitRegistry:
    """返回包含竞赛特有单位的 Pint 注册表。

    温度等带偏移单位由 Pint 的 Quantity 统一处理，避免把摄氏度错误地当作
    仅需乘法因子的普通长度单位。
    """
    registry = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
    registry.define("yuan = [currency]")
    registry.define("wan_yuan = 10000 * yuan")
    registry.define("missile_second = second")
    registry.define("person_trip = [person_trip]")
    registry.define("vehicle = [vehicle]")
    registry.define("car_kilometer = vehicle * kilometer")
    return registry


@lru_cache(maxsize=1)
def chinese_aliases() -> dict[str, str]:
    """读取仓内维护的中文别名表。"""
    aliases: dict[str, str] = {}
    path = Path(__file__).with_name("aliases_zh.txt")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        alias, target = (part.strip() for part in line.split("=", maxsplit=1))
        aliases[alias] = target
    return aliases
