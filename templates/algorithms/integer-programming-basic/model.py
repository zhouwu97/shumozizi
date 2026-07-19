"""枚举小规模整数可行域，作为优化模型基线。"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path


def main() -> None:
    """求解二变量、单资源约束的最大化问题。"""
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    best = None
    for x, y in itertools.product(range(data["x_max"] + 1), range(data["y_max"] + 1)):
        used = data["resource_x"] * x + data["resource_y"] * y
        if used <= data["capacity"]:
            objective = data["value_x"] * x + data["value_y"] * y
            if best is None or objective > best["objective"]:
                best = {"x": x, "y": y, "objective": objective, "resource_used": used}
    if best is None:
        raise ValueError("不存在整数可行解")
    Path(sys.argv[2]).write_text(json.dumps({"solution": best, "metrics": {"objective": best["objective"]}}), encoding="utf-8")


if __name__ == "__main__":
    main()
