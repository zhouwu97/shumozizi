"""验证每个子问题是否具备可直接回答的论文证据。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, relative_inside, resolve_inside
from shumozizi.core.schema import require_valid
from shumozizi.questions.manifest import verify_problem_manifest
from shumozizi.results.references import verify_referenced_result

CHECK_NAMES = (
    "question_requirements",
    "model_output",
    "output_mapping",
    "hard_constraints",
    "baseline",
    "accepted_result",
    "uncertainty",
    "direct_answer",
    "upstream_dependencies",
    "claim_status",
)


def _load_registry(run_dir: Path) -> dict[str, Any]:
    """读取结果注册表。"""
    registry = load_json(run_dir / "results" / "result_registry.json")
    require_valid(registry, "result_registry")
    return registry


def _verify_one(run_dir: Path, path: Path, registry: dict[str, Any]) -> list[str]:
    """验证一份逐问验收回执及其结果和章节绑定。"""
    errors: list[str] = []
    try:
        acceptance = load_json(path)
        require_valid(acceptance, "question_acceptance")
        if acceptance["run_id"] != run_dir.name:
            errors.append(f"{path.name}: run_id 与运行目录不一致")
        expected_question = path.parent.name
        if acceptance["question_id"] != expected_question:
            errors.append(f"{path.name}: question_id 与目录不一致")
        if acceptance["status"] != "accepted":
            errors.append(f"{path.name}: status 不是 accepted")
        if not acceptance["direct_answer"].strip():
            errors.append(f"{path.name}: direct_answer 为空")
        for check_name in CHECK_NAMES:
            if not acceptance["checks"][check_name]["passed"]:
                errors.append(f"{path.name}: 检查未通过 {check_name}")
        for result_id in acceptance["accepted_result_ids"]:
            errors.extend(
                f"{path.name}: {message}"
                for message in verify_referenced_result(
                    run_dir,
                    registry,
                    result_id,
                    question_id=acceptance["question_id"],
                )
            )
        for chapter in acceptance["chapter_paths"]:
            try:
                chapter_path = resolve_inside(run_dir, chapter, must_exist=True)
                if "paper/sections" not in relative_inside(run_dir, chapter_path).as_posix():
                    errors.append(f"{path.name}: 章节越出 paper/sections {chapter}")
            except ContractError as exc:
                errors.append(f"{path.name}: 章节无效 {exc}")
    except (ContractError, KeyError) as exc:
        errors.append(f"{path.name}: {exc}")
    return errors


def verify_question_acceptance(run_dir: Path) -> dict[str, Any]:
    """验证所有已完成问题的逐问验收回执。"""
    errors: list[str] = []
    try:
        state = load_json(run_dir / "state.json")
        registry = _load_registry(run_dir)
        manifest_report = verify_problem_manifest(run_dir)
        if not manifest_report["valid"]:
            errors.extend(f"问题全集: {message}" for message in manifest_report["errors"])
            manifest_questions: set[str] = set()
            required_questions: set[str] = set()
        else:
            manifest = load_json(run_dir / "problem/PROBLEM_MANIFEST.json")
            manifest_questions = {item["question_id"] for item in manifest["questions"]}
            required_questions = {
                item["question_id"] for item in manifest["questions"] if item["required"]
            }
        acceptance_dir = run_dir / "questions"
        completed = {
            question_id
            for question_id, tracks in state.get("question_progress", {}).items()
            if tracks.get("experiment") in {"ready", "accepted"}
        }
        seen: set[str] = set()
        for path in sorted(acceptance_dir.glob("*/QUESTION_ACCEPTANCE.json")):
            seen.add(path.parent.name)
            errors.extend(_verify_one(run_dir, path, registry))
        missing = sorted((completed | required_questions) - seen)
        errors.extend(f"问题缺少 QUESTION_ACCEPTANCE.json: {question_id}" for question_id in missing)
        errors.extend(
            f"QUESTION_ACCEPTANCE 引用了问题全集之外的题号: {question_id}"
            for question_id in sorted(seen - manifest_questions)
        )
    except (ContractError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}
