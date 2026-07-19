"""对一维参数执行确定种子蒙特卡洛敏感性分析。"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path


def main() -> None:
    """采样均匀扰动并输出均值与样本标准差。"""
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    generator = random.Random(int(data.get("seed", 42)))
    values = [data["center"] + generator.uniform(-data["radius"], data["radius"]) for _ in range(int(data["samples"]))]
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / max(1, len(values) - 1)
    Path(sys.argv[2]).write_text(json.dumps({"metrics": {"mean": average, "std": variance**0.5}, "sample_count": len(values)}), encoding="utf-8")


if __name__ == "__main__":
    main()
