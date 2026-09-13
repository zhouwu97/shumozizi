"""把分析、验证与审查台账重新绑定到源码哈希闭合的正式结果。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import atomic_json, json_bytes, sha256_bytes
from shumozizi.simple.results import read_result_index


MAPPING = {
    "q1-objective-production-v5-20260822-003": "q1-objective-production-v7-20260822-003",
    "q4-objective-production-v5-20260822-003": "q4-objective-production-v6-20260822-003",
    "q1-semantic-preflight-production-20260822-003": "q1-semantic-preflight-v2-20260822-003",
    "q4-semantic-preflight-production-20260822-003": "q4-semantic-preflight-v2-20260822-003",
}


def _atomic_text(path: Path, text: str) -> None:
    """在原文件同目录安全替换 UTF-8 文本。"""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main() -> int:
    """更新有限范围内的结果 ID，并修正 legacy quality 的结果摘要。"""
    parser = argparse.ArgumentParser(description="重新绑定正式结果 ID")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    index = read_result_index(run_dir)
    entries = {item["result_id"]: item for item in index["results"]}
    missing = [old for old, new in MAPPING.items() if new not in entries]
    if missing:
        raise RuntimeError("缺少待绑定的新正式结果: " + ", ".join(missing))

    targets: list[Path] = []
    targets.extend(sorted((run_dir / "analysis").glob("*.md")))
    targets.extend(sorted((run_dir / "analysis").glob("*.json")))
    targets.extend(
        [
            run_dir / "review" / "SCIENTIFIC_CHALLENGE.md",
            run_dir / "review" / "scientific_challenge_findings.json",
            run_dir / "results" / "verification" / "Q1_verification.json",
            run_dir / "results" / "verification" / "Q4_verification.json",
        ]
    )
    changed: list[str] = []
    for path in dict.fromkeys(targets):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        updated = text
        for old, new in MAPPING.items():
            updated = updated.replace(old, new)
        if updated != text:
            _atomic_text(path, updated)
            changed.append(path.relative_to(run_dir).as_posix())

    quality_path = run_dir / "results" / "quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    for assessment in quality.get("assessments", []):
        old = assessment.get("result_id")
        if old in MAPPING:
            new = MAPPING[old]
            assessment["result_id"] = new
            assessment["result_sha256"] = sha256_bytes(json_bytes(entries[new]))
    atomic_json(quality_path, quality)
    print(json.dumps({"mapping": MAPPING, "changed_files": changed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
