"""验证最终提交中的 Python 与 MATLAB/Octave 源码包。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, resolve_inside, sha256_file
from shumozizi.core.schema import require_valid

SOURCE_MANIFEST_PATH = "source/SOURCE_MANIFEST.json"
LANGUAGE_RULES = {
    "python": ("source/python/", ".py"),
    "matlab": ("source/matlab/", ".m"),
}


def verify_source_manifest(
    run_dir: Path,
    *,
    expected_final_pdf: Path | None = None,
) -> dict[str, Any]:
    """复验源码清单、双语言文件、产物引用和当前论文事实哈希。"""
    errors: list[str] = []
    manifest_path = run_dir / SOURCE_MANIFEST_PATH
    try:
        manifest = load_json(manifest_path)
        require_valid(manifest, "source_manifest")
        if manifest["run_id"] != run_dir.name:
            errors.append("SOURCE_MANIFEST.run_id 与运行目录不一致")

        paper_plan_path = run_dir / "paper/paper_plan.json"
        registry_path = run_dir / "results/result_registry.json"
        paper_plan = load_json(paper_plan_path)
        registry = load_json(registry_path)
        require_valid(paper_plan, "paper_plan")
        require_valid(registry, "result_registry")
        if paper_plan["run_id"] != run_dir.name or registry["run_id"] != run_dir.name:
            errors.append("源码包绑定的 paper_plan 或 result_registry run_id 不一致")

        final_pdf_path = resolve_inside(run_dir, paper_plan["final_pdf_path"], must_exist=True)
        if expected_final_pdf is not None and final_pdf_path != expected_final_pdf.resolve():
            errors.append("SOURCE_MANIFEST 绑定的最终 PDF 不是本次 QA 指定文件")
        expected_bindings = {
            "final_pdf": (paper_plan["final_pdf_path"], final_pdf_path),
            "paper_plan": ("paper/paper_plan.json", paper_plan_path),
            "result_registry": ("results/result_registry.json", registry_path),
        }
        for role, (relative, path) in expected_bindings.items():
            binding = manifest["bindings"][role]
            if binding["path"] != relative:
                errors.append(f"SOURCE_MANIFEST.{role}.path 必须为 {relative}")
            if binding["sha256"] != sha256_file(path):
                errors.append(f"SOURCE_MANIFEST 未绑定当前 {role} 哈希")

        question_ids, required_question_ids = _question_ids(run_dir)
        accepted_results = {
            item["result_id"]: item
            for item in registry["results"]
            if item["status"] == "accepted" and item["paper_allowed"]
        }
        figure_paths = {
            item["path"] for item in paper_plan["bindings"].get("figures_used", [])
        }
        claim_ids = _paper_claim_ids(run_dir)
        declared_paths: set[str] = set()
        covered_questions: set[str] = set()
        for language, (prefix, suffix) in LANGUAGE_RULES.items():
            for source in manifest["sources"][language]:
                relative = source["path"]
                if relative in declared_paths:
                    errors.append(f"源码文件在清单中重复声明: {relative}")
                    continue
                declared_paths.add(relative)
                if not relative.startswith(prefix) or not relative.lower().endswith(suffix):
                    errors.append(f"{language} 源码路径或扩展名不合法: {relative}")
                path = resolve_inside(run_dir, relative, must_exist=True)
                if source["sha256"] != sha256_file(path):
                    errors.append(f"源码哈希不一致: {relative}")
                unknown_questions = set(source["question_ids"]) - question_ids
                if unknown_questions:
                    errors.append(
                        f"源码 {relative} 引用了未知问题: {', '.join(sorted(unknown_questions))}"
                    )
                covered_questions.update(source["question_ids"])
                _verify_supports(
                    source,
                    accepted_results=accepted_results,
                    figure_paths=figure_paths,
                    claim_ids=claim_ids,
                    errors=errors,
                )

        actual_paths = {
            path.relative_to(run_dir).as_posix()
            for language, (prefix, suffix) in LANGUAGE_RULES.items()
            for path in (run_dir / prefix.rstrip("/")).rglob(f"*{suffix}")
            if path.is_file()
        }
        undeclared = sorted(actual_paths - declared_paths)
        missing = sorted(declared_paths - actual_paths)
        if undeclared:
            errors.append("源码目录存在未登记文件: " + ", ".join(undeclared))
        if missing:
            errors.append("清单登记的源码文件不存在: " + ", ".join(missing))
        uncovered = sorted(required_question_ids - covered_questions)
        if uncovered:
            errors.append("必做问题缺少源码覆盖: " + ", ".join(uncovered))
    except (ContractError, KeyError, OSError) as exc:
        errors.append(str(exc))
    return {
        "valid": not errors,
        "errors": errors,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
    }


def _question_ids(run_dir: Path) -> tuple[set[str], set[str]]:
    """读取权威问题全集并返回全部及必做问题 ID。"""
    manifest = load_json(run_dir / "problem/PROBLEM_MANIFEST.json")
    require_valid(manifest, "problem_manifest")
    all_ids = {item["question_id"] for item in manifest["questions"]}
    required_ids = {
        item["question_id"] for item in manifest["questions"] if item["required"]
    }
    return all_ids, required_ids


def _paper_claim_ids(run_dir: Path) -> set[str]:
    """返回论文证据图中允许被源码声明支持的 claim ID。"""
    path = run_dir / "paper/evidence_map.json"
    if not path.is_file():
        return set()
    document = load_json(path)
    require_valid(document, "evidence_map")
    return {item["claim_id"] for item in document["claims"]}


def _verify_supports(
    source: dict[str, Any],
    *,
    accepted_results: dict[str, dict[str, Any]],
    figure_paths: set[str],
    claim_ids: set[str],
    errors: list[str],
) -> None:
    """验证单个源码文件对结果、图表或论文结论的引用。"""
    for support in source["supports"]:
        kind, reference = support["kind"], support["ref"]
        if kind == "accepted_result":
            result = accepted_results.get(reference)
            if result is None:
                errors.append(f"源码引用的结果不是 accepted 且 paper_allowed: {reference}")
            elif result["question_id"] not in source["question_ids"]:
                errors.append(
                    f"源码对结果 {reference} 的引用未包含其问题 {result['question_id']}"
                )
        elif kind == "figure" and reference not in figure_paths:
            errors.append(f"源码引用的图表未进入当前 paper_plan: {reference}")
        elif kind == "paper_claim" and reference not in claim_ids:
            errors.append(f"源码引用的论文结论不存在于 evidence_map: {reference}")
