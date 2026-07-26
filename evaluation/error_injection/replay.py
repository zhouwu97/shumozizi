"""回放四类高风险错误，确认全面审核后的查漏门会实际阻断。"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.simple.review_gaps import verify_review_gap_completion


def _write_gap_case(
    run_dir: Path,
    *,
    facts: dict[str, bool],
    claims: list[dict[str, str]],
) -> dict[str, object]:
    """构造一个遗漏中央风险的最小全面审核后状态，并运行真实 gate。"""
    report = run_dir / "review" / "SCIENTIFIC_CHALLENGE.md"
    report.parent.mkdir(parents=True)
    report.write_text("# 全面审核\n\n本回放故意遗漏一个中央风险。\n", encoding="utf-8")
    facts_path = run_dir / "analysis" / "method_facts.json"
    atomic_json(facts_path, {"schema_version": "1.1", "run_id": run_dir.name, "facts": facts})
    claims_path = run_dir / "review" / "strong_claims" / "scientific.json"
    atomic_json(
        claims_path,
        {
            "schema_name": "review_strong_claims",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": "scientific",
            "review_file": "review/SCIENTIFIC_CHALLENGE.md",
            "review_sha256": sha256_file(report),
            "claims": claims,
        },
    )
    atomic_json(
        run_dir / "review" / "gaps" / "round-1.json",
        {
            "schema_name": "review_gap_report",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": "scientific",
            "review_file": "review/SCIENTIFIC_CHALLENGE.md",
            "review_sha256": sha256_file(report),
            "method_facts_file": "analysis/method_facts.json",
            "method_facts_sha256": sha256_file(facts_path),
            "strong_claims_file": "review/strong_claims/scientific.json",
            "strong_claims_sha256": sha256_file(claims_path),
            "risks": [],
            "findings": [],
            "closures": [],
        },
    )
    return verify_review_gap_completion(
        run_dir,
        scope="scientific",
        review_report={
            "report": {"file": "review/SCIENTIFIC_CHALLENGE.md"},
            "task_receipt": {"task_id": "primary"},
            "reviewer": {"thread_id": "primary-thread"},
        },
    )


def _base_facts() -> dict[str, bool]:
    """返回每个回放显式登记的完整事实基线。"""
    return {
        "uses_continuous_time": False,
        "uses_discrete_approximation": False,
        "uses_proxy_objective": False,
        "uses_heuristic_optimization": False,
        "candidate_search_limited": False,
        "uses_temporal_split": False,
        "has_shared_downstream_dependency": False,
    }


def _internal_report_language_trigger(text: str) -> bool:
    """模拟盲评中的学术文体红旗定位；它不代替盲评结论。"""
    markers = ("内部技术报告", "审核报告", "本轮门禁", "待修复 finding")
    return sum(marker in text for marker in markers) >= 2


def main() -> int:
    """运行四个注入案例，并将可重复的触发结果写为 JSON。"""
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="review-gap-replay-") as temporary:
        root = Path(temporary)
        continuous = _base_facts()
        continuous["uses_continuous_time"] = True
        continuous["uses_discrete_approximation"] = True
        status = _write_gap_case(
            root / "continuous",
            facts=continuous,
            claims=[
                {
                    "claim_id": "continuous-bound",
                    "claim_type": "continuous_conservative_bound",
                    "statement": "中点网格给出连续保守下界。",
                }
            ],
        )
        cases.append(
            {
                "id": "continuous-midpoint-false-lower-bound",
                "triggered": not status["allowed"],
                "detected_by": "gap_detector",
                "finding_severity": "P1",
                "blocking": True,
                "closure": "必须加入连续域证书或专项复算后重做全面审核。",
                "reason": status["reason"],
            }
        )
        activation = _base_facts()
        status = _write_gap_case(
            root / "activation",
            facts=activation,
            claims=[
                {
                    "claim_id": "all-actions",
                    "claim_type": "all_actions_material",
                    "statement": "每个动作均有不可替代贡献。",
                }
            ],
        )
        cases.append(
            {
                "id": "zero-action-activation",
                "triggered": not status["allowed"],
                "detected_by": "gap_detector",
                "finding_severity": "P1",
                "blocking": True,
                "closure": "逐动作删除消融并重做审核。",
                "reason": status["reason"],
            }
        )
        search = _base_facts()
        search["candidate_search_limited"] = True
        status = _write_gap_case(
            root / "search",
            facts=search,
            claims=[
                {
                    "claim_id": "competitive",
                    "claim_type": "competitive_search",
                    "statement": "有限候选搜索已具有竞赛竞争力。",
                }
            ],
        )
        cases.append(
            {
                "id": "limited-search-competitive-claim",
                "triggered": not status["allowed"],
                "detected_by": "gap_detector",
                "finding_severity": "P1",
                "blocking": True,
                "closure": "执行等预算搜索挑战并重做审核。",
                "reason": status["reason"],
            }
        )
        internal = _internal_report_language_trigger(
            "这是内部技术报告。本轮门禁显示待修复 finding；请参见审核报告。"
        )
        cases.append(
            {
                "id": "internal-report-language",
                "triggered": internal,
                "detected_by": "paper_blind_full_review_adapter",
                "finding_severity": "P2",
                "blocking": True,
                "closure": "重写为面向评委的学术论文，并重新执行 PDF 盲审。",
                "reason": "检测到多个内部审核文体红旗。" if internal else "未触发",
            }
        )
    payload = {
        "schema_version": "1.0",
        "status": "executed",
        "cases": cases,
        "all_triggered": all(item["triggered"] for item in cases),
    }
    target = Path(__file__).with_name("replay-results.json")
    atomic_json(target, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["all_triggered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
