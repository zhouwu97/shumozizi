"""在非负权网络上计算最短路径。"""

from __future__ import annotations

import heapq
import json
import sys
from pathlib import Path


def main() -> None:
    """读取边表 JSON 并输出起终点最短路。"""
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    graph: dict[str, list[tuple[str, float]]] = {}
    for source, target, weight in data["edges"]:
        if weight < 0:
            raise ValueError("Dijkstra 不接受负权边")
        graph.setdefault(source, []).append((target, float(weight)))
        if not data.get("directed", False):
            graph.setdefault(target, []).append((source, float(weight)))
    queue = [(0.0, data["source"], [data["source"]])]
    visited: set[str] = set()
    answer = None
    while queue:
        distance, node, path = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        if node == data["target"]:
            answer = {"distance": distance, "path": path}
            break
        for neighbor, weight in graph.get(node, []):
            if neighbor not in visited:
                heapq.heappush(queue, (distance + weight, neighbor, [*path, neighbor]))
    if answer is None:
        raise ValueError("起终点不可达")
    Path(sys.argv[2]).write_text(json.dumps({"solution": answer, "metrics": {"distance": answer["distance"]}}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
