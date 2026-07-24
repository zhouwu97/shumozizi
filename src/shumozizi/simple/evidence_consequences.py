"""把任意独立引擎的负面科学证据级联到下游产物。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.critical_claims import read_critical_claims
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_state,
    read_simple_state,
    update_simple_state,
    utc_now,
)

CONSEQUENCES_PATH = Path("review/evidence-consequences.json")


def _negative_event(kind: str, evidence: dict[str, Any]) -> str | None:
    """将不同证据协议归一化为通用阻断事件。"""
    verdict = evidence.get("verdict")
    if verdict == "feasibility_failed":
        return "feasibility_failed"
    if kind in {"independent-recompute", "alternative-formula"} and verdict == "inconsistent":
        return "inconsistent"
    if kind == "counterexample" and verdict == "counterexample_found":
        return "counterexample_found"
    if kind == "small-enumeration" and evidence.get("mismatches", 0) > 0:
        return "enumeration_mismatch"
    if kind in {"property-test", "geometry-continuous-validation"} and verdict == "fail":
        return "property_failed"
    if kind in {"search-challenge", "action-activation-challenge"} and verdict == "incumbent_not_competitive":
        return "incumbent_not_competitive"
    if kind == "fixed-action-utilization" and verdict in {"underutilized_required_action", "invalid"}:
        return "all_actions_not_material"
    return None


def _question_for_record(record: dict[str, Any], claims: dict[str, dict[str, Any]]) -> str | None:
    """优先使用显式 question_id，其次经关键主张映射，绝不解析 ID 前缀。"""
    evidence = record["semantic_output"]
    qid = evidence.get("question_id")
    if isinstance(qid, str) and qid:
        return qid
    claim_id = evidence.get("claim_id")
    claim = claims.get(claim_id)
    return claim.get("question_id") if claim else None


def _schema() -> dict[str, Any]:
    """返回后果事件日志 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/evidence_consequences.schema.json")


def apply_independent_evidence_consequences(
    run_dir: Path, records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """先执行所有负面证据后果，再允许上层检查审核 verdict。"""
    negative = [
        (record, _negative_event(record["kind"], record["semantic_output"]))
        for record in records
    ]
    negative = [(record, event) for record, event in negative if event is not None]
    if not negative:
        return []

    state = read_simple_state(run_dir)
    previous_phase = state["phase"]
    claims_path = run_dir / "analysis" / "critical_claims.json"
    if claims_path.is_file():
        claim_document = read_critical_claims(run_dir)
    elif is_competition_first_state(state):
        # v3.1 只将答案映射用于防漏问，不能再要求每问都有关键主张合同。
        claim_document = None
    else:
        claim_document = read_critical_claims(run_dir)
    claims = {
        item["claim_id"]: item
        for item in (claim_document or {}).get("claims", [])
    }
    index = read_result_index(run_dir)
    figure_path = run_dir / "figures" / "index.json"
    figures = load_json(figure_path) if figure_path.is_file() else {"figures": []}
    quality_path = run_dir / "results" / "quality.json"
    quality = load_json(quality_path) if quality_path.is_file() else {"assessments": []}
    argument_paths = [
        run_dir / "paper" / "generated" / "argument_map.json",
        run_dir / "paper" / "argument_map.json",
    ]
    argument_maps = [
        (path, load_json(path)) for path in argument_paths if path.is_file()
    ]
    events: list[dict[str, Any]] = []

    try:
        for record, event_name in negative:
            qid = _question_for_record(record, claims)
            if not qid:
                raise ContractError(f"负面证据 {record['evidence_id']} 缺少显式 question_id/claim 归属")
            affected = {qid}
            for result in index["results"]:
                if result.get("status") != "current" or qid not in result.get("affected_question_ids", [result.get("question_id")]):
                    continue
                if result.get("dependency_scope") in {"shared", "global"}:
                    affected.update(result.get("affected_question_ids", []))
            invalidated_results: list[str] = []
            for result in index["results"]:
                result_scope = set(result.get("affected_question_ids", [result.get("question_id")]))
                if result.get("status") == "current" and result_scope & affected:
                    result["status"] = "superseded"
                    invalidated_results.append(result["result_id"])
            invalidated_claims = sorted(
                claim_id for claim_id, claim in claims.items()
                if claim["question_id"] in affected
                or set(claim.get("result_ids", [])) & set(invalidated_results)
            )
            if claim_document is not None:
                claim_document["invalidated_claims"] = sorted(
                    set(claim_document.get("invalidated_claims", []))
                    | set(invalidated_claims)
                )
                claim_document["invalidation_reason"] = (
                    f"independent_evidence:{event_name}"
                )
            for assessment in quality.get("assessments", []):
                if assessment.get("result_id") in invalidated_results:
                    assessment["result_role"] = "candidate"
                    assessment["paper_allowed"] = False
                    assessment.setdefault("reasons", []).append(f"independent_evidence:{event_name}")
            invalidated_figures: list[str] = []
            for figure in figures.get("figures", []):
                source_ids = set(figure.get("source_result_ids", [figure.get("result_id")]))
                if figure.get("status") == "current" and source_ids & set(invalidated_results):
                    figure["status"] = "superseded"
                    figure["superseded_reason"] = f"independent_evidence:{event_name}"
                    invalidated_figures.append(figure["figure_id"])
            for _, argument_map in argument_maps:
                argument_map["status"] = "superseded"
                argument_map["superseded_reason"] = f"independent_evidence:{event_name}"
            events.append({
                "event_id": f"consequence-{record['evidence_id']}",
                "source_evidence_id": record["evidence_id"],
                "source_receipt_sha256": record["receipt"]["sha256"],
                "negative_event": event_name,
                "severity": "blocking",
                "affected_question_ids": sorted(affected),
                "invalidated_claims": invalidated_claims,
                "invalidated_results": sorted(invalidated_results),
                "invalidated_figures": sorted(invalidated_figures),
                "previous_phase": previous_phase,
                "new_phase": "experiment",
                "created_at": utc_now(),
            })
        atomic_json(run_dir / "results" / "index.json", index)
        if claim_document is not None:
            atomic_json(claims_path, claim_document)
        if quality_path.is_file():
            atomic_json(quality_path, quality)
        if figure_path.is_file():
            atomic_json(figure_path, figures)
        for argument_path, argument_map in argument_maps:
            atomic_json(argument_path, argument_map)
        compile_path = run_dir / "paper" / "compile-receipt.json"
        if compile_path.is_file():
            archive = run_dir / "paper" / "compile-receipt.superseded.json"
            suffix = 2
            while archive.exists():
                archive = run_dir / "paper" / f"compile-receipt.superseded-{suffix}.json"
                suffix += 1
            compile_path.rename(archive)
        summary_path = run_dir / "review" / "summary.json"
        if summary_path.is_file():
            summary = load_json(summary_path)
            summary["scientific_review"]["verdict"] = "revoked"
            summary["paper_blind_review"] = None
            summary["final_audit"] = None
            summary["updated_at"] = utc_now()
            atomic_json(summary_path, summary)
        log_path = run_dir / CONSEQUENCES_PATH
        log = load_json(log_path) if log_path.is_file() else {
            "schema_name": "evidence_consequences",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "events": [],
        }
        existing_ids = {item["event_id"] for item in log["events"]}
        log["events"].extend(item for item in events if item["event_id"] not in existing_ids)
        errors = [
            error.message
            for error in Draft202012Validator(
                _schema(), format_checker=FormatChecker()
            ).iter_errors(log)
        ]
        if errors:
            raise ContractError("负面证据事件日志不符合 Schema: " + "；".join(errors))
        atomic_json(log_path, log)
        update_simple_state(run_dir, phase="experiment")
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        try:
            update_simple_state(run_dir, phase="blocked")
        except ContractError as state_exc:
            raise ContractError(f"负面证据级联失败且无法进入 blocked: {exc}; {state_exc}") from exc
        raise ContractError(f"负面证据级联失败，运行已进入 blocked: {exc}") from exc

    return events
