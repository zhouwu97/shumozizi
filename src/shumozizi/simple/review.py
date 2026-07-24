"""管理 v3 的冻结审查包与独立审查放行边界。"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now, update_simple_state

REVIEW_ROOT = Path("review")
SUMMARY_PATH = REVIEW_ROOT / "summary.json"
OBJECTIVE_SEMANTICS_REPORT_PATH = REVIEW_ROOT / "OBJECTIVE_SEMANTICS_REVIEW.md"
OBJECTIVE_SEMANTICS_ASSESSMENT_PATH = REVIEW_ROOT / "OBJECTIVE_SEMANTICS.json"
OBJECTIVE_SEMANTICS_RECEIPT_PATH = REVIEW_ROOT / "objective-semantics.json"
AMBIGUITY_DECISIONS_PATH = Path("state/ambiguity-decisions.json")
SCIENTIFIC_REPORT_PATH = REVIEW_ROOT / "SCIENTIFIC_RED_TEAM.md"
PAPER_BLIND_REPORT_PATH = REVIEW_ROOT / "PAPER_BLIND_REVIEW.md"
FINAL_AUDIT_REPORT_PATH = REVIEW_ROOT / "FINAL_SUBMISSION_REVIEW.md"
RED_TEAM_ARTIFACTS_PATH = REVIEW_ROOT / "red_team_artifacts"
_PACKET_ROOTS = {
    "objective-semantics": ("problem",),
    "scientific": ("problem", "code", "results/raw"),
    "paper-blind": ("problem", "paper/final.pdf", "paper/submission"),
    "final-audit": ("problem", "paper/final.pdf", "paper/submission"),
}
_PACKET_DESTINATIONS = {
    "problem": "problem",
    "code": "source_snapshot",
    "results/raw": "candidate_results",
    "paper/final.pdf": "paper/final.pdf",
    "paper/submission": "submission",
    "results": "results",
    "figures": "figures",
    "reports": "reports",
    "qa/mechanical-qa.json": "qa/mechanical-qa.json",
}
_REQUIRED_PACKET_ROOTS = {
    "objective-semantics": frozenset(("problem",)),
    "scientific": frozenset(("problem", "code", "results/raw")),
    "paper-blind": frozenset(("problem", "paper/final.pdf", "paper/submission")),
    "final-audit": frozenset(("problem", "paper/final.pdf", "paper/submission")),
}
_SEVERITIES = {"none", "P0", "P1", "P2", "P3"}
_VERDICTS = {"pass", "fail", "needs_rework", "revoked"}
_VISUALIZATION_CODE_DIRECTORY = Path("figures")
_RED_TEAM_KINDS = {
    "independent-recompute",
    "counterexample",
    "small-enumeration",
    "alternative-formula",
    "search-challenge",
    "property-test",
    "action-activation-challenge",
    "fixed-action-utilization",
    "geometry-continuous-validation",
}
_SAFE_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_REPORT_ARTIFACT_PATH = re.compile(r"review[\\/]red_team_artifacts[\\/][A-Za-z0-9._/\\-]+")

# 科学审查包白名单：文件名不得包含这些标签片段
_PACKET_LABEL_EXCLUDE = re.compile(
    r"(quality|verified|accepted|best|final|paper_allowed|search_adequacy|"
    r"competition_strength|qualified|strong|current|candidate_accepted)",
    re.IGNORECASE,
)

# 科学审查包内容级去标签：从结果 JSON 中删除这些键
_PACKET_CONTENT_EXCLUDE_KEYS = frozenset({
    "accepted", "paper_allowed", "search_adequacy",
    "competition_strength", "qualified", "strong",
    "result_role", "quality", "verified",
    "candidate_accepted", "best_candidate",
    "promotion_allowed", "pass_allowed",
})


def _packet_should_exclude(path: Path) -> bool:
    """判断文件是否应被排除在科学审查包之外。

    检查文件名是否含质量标签。
    """
    if _PACKET_LABEL_EXCLUDE.search(path.name):
        return True
    return False


def _neutralize_candidate_json(source: Path, target: Path) -> None:
    """生成中性候选结果：复制 JSON 并删除质量裁决字段。

    不直接修改源文件。
    """
    import json as _json

    try:
        data = _json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        shutil.copy2(source, target)
        return
    if isinstance(data, dict):
        for key in list(data):
            if key in _PACKET_CONTENT_EXCLUDE_KEYS:
                del data[key]
    target.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _infer_source_root(source_relative: str) -> str:
    """从文件路径推导所属源根（results/raw、code 或 problem）。"""
    if source_relative.startswith("results/raw"):
        return "results/raw"
    if source_relative.startswith("code/"):
        return "code"
    return "problem"


def _source_is_candidate_results(source_relative: str) -> bool:
    """判断源目录是否为科学审查包的候选结果目录。"""
    return source_relative == "results/raw"


def _schema() -> dict[str, Any]:
    """读取独立审查摘要的 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "simple_review_summary.schema.json")


def _objective_schema(name: str) -> dict[str, Any]:
    """读取目标语义预审的评估或收据 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / f"{name}.schema.json")


def _validate_document(payload: dict[str, Any], schema_name: str, label: str) -> None:
    """用指定 Schema 校验目标语义文档并返回可读错误。"""
    validator = Draft202012Validator(
        _objective_schema(schema_name), format_checker=FormatChecker()
    )
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError(f"{label}不符合协议: " + "; ".join(errors))


def _require_summary(payload: dict[str, Any]) -> None:
    """确保审查摘要格式正确且语义不自相矛盾。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))
    scientific = payload["scientific_review"]
    if scientific["verdict"] == "pass" and scientific["highest_severity"] in {"P0", "P1"}:
        raise ContractError("科学审查含 P0/P1 时不能给出 pass")
    if scientific["verdict"] == "pass" and scientific["full_rerun_required"]:
        raise ContractError("要求全量重跑的科学审查不能给出 pass")
    paper = payload["paper_blind_review"]
    if (
        paper is not None
        and paper["verdict"] == "pass"
        and paper["highest_severity"] in {"P0", "P1"}
    ):
        raise ContractError("盲审含 P0/P1 时不能给出 pass")
    if payload["schema_version"] == "1.4" and paper is not None and paper["verdict"] == "pass":
        assessment = paper["assessment"]
        if (
            not assessment["argumentation_complete"]
            or not assessment["readability_passed"]
            or assessment["empty_sections"]
            or assessment["unreadable_pages"]
        ):
            raise ContractError("盲审未确认逐问论证完整和页面可读时不能给出 pass")
    final_audit = payload.get("final_audit")
    if (
        final_audit is not None
        and final_audit["verdict"] == "pass"
        and final_audit["highest_severity"] in {"P0", "P1"}
    ):
        raise ContractError("最终交付审核含 P0/P1 时不能给出 pass")


def _red_team_schema() -> dict[str, Any]:
    """读取红队可执行证据收据 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "red_team_evidence_receipt.schema.json")


def _require_red_team_receipt(payload: dict[str, Any]) -> None:
    """验证红队脚本的最小可执行证据收据。"""
    validator = Draft202012Validator(_red_team_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("红队证据收据无效: " + "; ".join(errors))


def _red_team_semantic_schema() -> dict[str, Any]:
    """读取各类红队输出的最小科学语义 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "red_team_semantic_output.schema.json")


def _require_red_team_semantic_output(kind: str, path: Path) -> dict[str, Any]:
    """验证红队输出不仅执行成功，而且包含可复验的科学比较。"""
    try:
        evidence = load_json(path)
    except (OSError, ValueError) as exc:
        raise ContractError(f"红队语义输出不是有效 JSON: {path.name}") from exc
    payload = {"kind": kind, "evidence": evidence}
    validator = Draft202012Validator(
        _red_team_semantic_schema(), format_checker=FormatChecker()
    )
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("红队语义输出无效: " + "; ".join(errors))

    if kind in {"independent-recompute", "alternative-formula"}:
        expected = abs(evidence["production_value"] - evidence["independent_value"])
        if not math.isclose(
            evidence["absolute_difference"], expected, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ContractError("红队语义输出的 absolute_difference 与复算值不一致")
    elif kind == "counterexample":
        if evidence["expected"] == evidence["production_observed"]:
            raise ContractError("红队语义输出未形成预期与生产观察之间的反例")
    elif kind == "small-enumeration":
        consistent = evidence["mismatches"] == 0
        if (evidence["verdict"] == "consistent") != consistent:
            raise ContractError("红队语义输出的枚举 mismatches 与 verdict 不一致")
    elif kind == "search-challenge":
        if evidence["independent_candidates"] > evidence["evaluation_budget"]:
            raise ContractError("红队语义输出的独立候选数超过评价预算")
        if evidence["feasible_candidates"] > evidence["independent_candidates"]:
            raise ContractError("红队语义输出的可行候选数超过独立候选数")
    elif kind == "property-test":
        passed = evidence["failures"] == 0
        if (evidence["verdict"] == "pass") != passed:
            raise ContractError("红队语义输出的 property failures 与 verdict 不一致")
    elif kind == "action-activation-challenge":
        _validate_action_activation_evidence(evidence)
    elif kind == "geometry-continuous-validation":
        _validate_geometry_continuous_evidence(evidence)
    return evidence


def _validate_geometry_continuous_evidence(evidence: dict[str, Any]) -> None:
    """拒绝用内部随机采样冒充连续几何边界证明。"""
    sampled = evidence["sampled_approximation"]
    if sampled is not None and sampled == evidence["continuous_quantity"]:
        raise ContractError("连续几何量与采样近似必须使用不同变量名")
    if evidence["verification_method"] == "explicit_discretization_error" and evidence[
        "discretization_error_bound"
    ] is None:
        raise ContractError("显式离散化验证必须给出 discretization_error_bound")
    covered = all(evidence["critical_cases"].values())
    expected = "pass" if covered else "fail"
    if evidence["verdict"] != expected:
        raise ContractError("连续几何验证 verdict 与临界边界覆盖不一致")


def _validate_action_activation_evidence(evidence: dict[str, Any]) -> None:
    """复算可变动作数量挑战的覆盖充分性与 incumbent 结论。"""
    allowed = evidence["allowed_action_count"]
    active = evidence["incumbent_active_count"]
    unused = active < allowed
    if evidence["unused_actions_exist"] != unused:
        raise ContractError("动作激活挑战的 unused_actions_exist 与动作数量不一致")
    direction = evidence["objective_direction"]
    tolerance = float(evidence["improvement_tolerance"])
    trace = [float(value) for value in evidence["best_so_far"]]
    monotone = all(
        current >= previous - tolerance
        if direction == "maximize"
        else current <= previous + tolerance
        for previous, current in zip(trace, trace[1:], strict=False)
    )
    if not monotone:
        raise ContractError("动作激活挑战的 best_so_far 未按目标方向单调更新")
    challenge_best = float(evidence["challenge_best_exact"])
    if not math.isclose(trace[-1], challenge_best, rel_tol=0.0, abs_tol=tolerance):
        raise ContractError("动作激活挑战的 best_so_far 末值与 challenge_best_exact 不一致")
    rounds = evidence["rounds"]
    if sum(item["evaluation_count"] for item in rounds) > evidence["evaluation_budget"]:
        raise ContractError("动作激活挑战轮次消耗超过冻结评价预算")
    if any(item["active_count"] > allowed for item in rounds):
        raise ContractError("动作激活挑战轮次使用了题面不允许的动作数量")
    if evidence["first_feasible_evaluation"] is not None and (
        evidence["first_feasible_evaluation"] > evidence["evaluation_budget"]
    ):
        raise ContractError("动作激活挑战首次可行位置超过评价预算")

    incumbent = float(evidence["incumbent_exact"])
    improved = (
        challenge_best > incumbent + tolerance
        if direction == "maximize"
        else challenge_best < incumbent - tolerance
    )
    method = evidence["coverage_method"]
    details = evidence["coverage_details"]
    sufficient = not unused
    if unused and method == "structural_proof":
        sufficient = bool(_SHA256.fullmatch(str(details.get("proof_sha256", ""))))
    elif unused and method == "small_complete_enumeration":
        enumerated = details.get("enumerated_configurations")
        total = details.get("total_configurations")
        sufficient = (
            isinstance(enumerated, int)
            and not isinstance(enumerated, bool)
            and isinstance(total, int)
            and not isinstance(total, bool)
            and total > 0
            and enumerated == total
        )
    elif unused and method == "insertion_local_optimization":
        required_rounds = min(2, allowed - active)
        covered = {item["active_count"] for item in rounds if item["evaluation_count"] > 0}
        required_counts = set(range(active + 1, active + required_rounds + 1))
        sufficient = (
            required_counts <= covered
            and evidence["consecutive_no_improvement_rounds"] >= required_rounds
        )
    elif unused and method == "independent_full_count_search":
        covered = set(details.get("covered_action_counts", []))
        sufficient = set(range(active + 1, allowed + 1)) <= covered

    expected_verdict = (
        "incumbent_not_competitive"
        if improved
        else "incumbent_competitive"
        if sufficient
        else "inconclusive"
    )
    if evidence["verdict"] != expected_verdict:
        raise ContractError(
            "动作激活挑战 verdict 与 exact 改善及搜索空间覆盖结论不一致"
        )


def _summarize_evidence_verdicts(
    evidence_items: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """聚合红队证据的科学结论，生成不可被人工标签覆盖的门禁。

    Args:
        evidence_items: ``(证据类型, 语义输出)`` 列表。

    Returns:
        是否允许科学通过、是否允许提升竞赛强度及对应原因。
    """
    blocking_reasons: list[str] = []
    promotion_blockers: list[str] = []
    for kind, evidence in evidence_items:
        verdict = evidence.get("verdict")
        if kind in {"independent-recompute", "alternative-formula"}:
            if verdict == "inconsistent":
                blocking_reasons.append(f"{kind}:inconsistent")
        elif kind == "counterexample":
            if verdict == "counterexample_found":
                blocking_reasons.append(f"{kind}:counterexample_found")
        elif kind == "small-enumeration":
            mismatches = evidence.get("mismatches", 0)
            if isinstance(mismatches, int) and mismatches > 0:
                blocking_reasons.append(f"{kind}:mismatches={mismatches}")
        elif kind == "property-test":
            failures = evidence.get("failures", 0)
            if verdict == "fail" or (isinstance(failures, int) and failures > 0):
                blocking_reasons.append(f"{kind}:failures={failures}")
        elif kind == "search-challenge" and verdict in {
            "incumbent_not_competitive",
            "inconclusive",
        }:
            promotion_blockers.append(f"{kind}:{verdict}")
        elif kind == "action-activation-challenge":
            if verdict == "incumbent_not_competitive":
                blocking_reasons.append(f"{kind}:{verdict}")
            elif verdict == "inconclusive":
                promotion_blockers.append(f"{kind}:{verdict}")
        elif kind == "geometry-continuous-validation" and verdict == "fail":
            blocking_reasons.append(f"{kind}:fail")
    if blocking_reasons:
        promotion_blockers.extend(blocking_reasons)
    return {
        "pass_allowed": not blocking_reasons,
        "promotion_allowed": not promotion_blockers,
        "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
        "promotion_blockers": list(dict.fromkeys(promotion_blockers)),
    }


def _red_team_root(run_dir: Path) -> Path:
    """返回当前运行中唯一允许保存红队产物的目录。"""
    return (run_dir.resolve() / RED_TEAM_ARTIFACTS_PATH).resolve()


def _file_evidence(run_dir: Path, path: Path) -> dict[str, Any]:
    """为运行内文件生成冻结路径、哈希和大小。"""
    relative = relative_inside(run_dir, path)
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _require_red_team_artifact_path(run_dir: Path, relative: str, *, must_exist: bool) -> Path:
    """限制脚本、输出和日志全部留在审查证据目录。"""
    path = resolve_inside(run_dir, relative, must_exist=must_exist)
    root = _red_team_root(run_dir)
    if path != root and root not in path.parents:
        raise ContractError("红队脚本和输出必须位于 review/red_team_artifacts/ 内")
    return path


def _red_team_engine_command(run_dir: Path, engine: str) -> str:
    """只接受能力路由已实际探测且选择的红队执行引擎。"""
    if engine not in {"python", "matlab", "octave"}:
        raise ContractError("红队证据仅支持 python、matlab 或 octave")
    route = require_capability_route(run_dir)
    toolchain = route["toolchain"]
    selected = {toolchain["production_engine"]}
    if toolchain.get("independent_engine") is not None:
        selected.add(toolchain["independent_engine"])
    if engine not in selected:
        raise ContractError("红队引擎必须是当前能力路由选择的生产或独立引擎")
    tooling = load_json(run_dir / "state" / "tooling.json")
    for record in tooling.get("engines", []):
        if not isinstance(record, dict) or record.get("engine") != engine:
            continue
        command = record.get("command")
        probe = record.get("probe")
        if (
            record.get("available") is True
            and isinstance(command, str)
            and isinstance(probe, dict)
            and probe.get("exit_code") == 0
            and probe.get("timed_out") is False
        ):
            return command
    raise ContractError(f"红队引擎未通过当前运行的烟雾测试: {engine}")


def _safe_red_team_argument(value: str) -> str:
    """限制不经 Shell 传递给 Python 红队脚本的附加参数。"""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError("红队脚本参数必须是非空字符串")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError("红队脚本参数包含不安全路径")
    return value


def _packet_input_files(packet_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """返回审查脚本可读取的冻结 packet 文件，而不接受任意 run 输入。"""
    files: list[Path] = []
    for item in manifest["files"]:
        packet_relative = item["packet"]
        files.append(_safe_packet_path(packet_dir, packet_relative, must_exist=True))
    return files


def _red_team_command(
    engine: str, command: str, script_name: str, arguments: list[str]
) -> list[str]:
    """构造在清洁目录执行的无 Shell 红队命令。"""
    if engine == "python":
        return [command, "-I", script_name, "packet", "outputs", *arguments]
    if "'" in script_name:
        raise ContractError("MATLAB/Octave 红队脚本名不允许单引号")
    if arguments:
        raise ContractError("MATLAB/Octave 红队脚本请通过环境变量读取 packet 与输出目录")
    expression = f"run('{script_name}')"
    if engine == "matlab":
        return [command, "-batch", expression]
    return [command, "--quiet", "--no-gui", "--eval", expression]


def run_red_team_evidence(
    run_dir: Path,
    *,
    evidence_id: str,
    kind: str,
    packet_manifest: str,
    script_path: str,
    output_paths: list[str],
    engine: str = "python",
    arguments: list[str] | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """在冻结 scientific packet 的清洁目录实际执行一项红队证据。

    审查脚本只会接收到 packet 副本和空输出目录。该边界减少了无意读取生产
    上下文的风险，但不把任意本地脚本误称为操作系统级沙箱；新对话隔离仍由
    Codex 协调层负责。

    Args:
        run_dir: 当前 v3 运行目录。
        evidence_id: 本次攻击的安全唯一标识。
        kind: 攻击产物类型。
        packet_manifest: 已冻结 scientific 审查包清单的运行内路径。
        script_path: 红队脚本的运行内相对路径。
        output_paths: 脚本在 ``outputs/`` 下新建的相对输出名。
        engine: 已由能力路由烟雾测试的 Python、MATLAB 或 Octave。
        arguments: 仅 Python 脚本使用的受控参数。
        timeout_seconds: 命令最长运行秒数。

    Returns:
        写入的红队证据收据。

    Raises:
        ContractError: packet、命令或输出不满足独立可执行证据边界。
    """
    if not _SAFE_EVIDENCE_ID.fullmatch(evidence_id):
        raise ContractError("红队 evidence_id 不合法")
    if kind not in _RED_TEAM_KINDS:
        raise ContractError("不支持的红队证据类型")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("红队证据 timeout_seconds 必须在 1 至 3600 之间")
    root = run_dir.resolve()
    manifest_path, manifest = _read_packet_manifest(root, packet_manifest)
    if manifest["packet_kind"] != "scientific":
        raise ContractError("红队证据只能读取 scientific 冻结审查包")
    packet_status = verify_review_packet(root, packet_manifest)
    if not packet_status["success"]:
        raise ContractError("红队 scientific 审查包已失效: " + "；".join(packet_status["errors"]))
    artifact_root = _red_team_root(root)
    artifact_root.mkdir(parents=True, exist_ok=True)
    original_script = _require_red_team_artifact_path(root, script_path, must_exist=True)
    suffix = {"python": ".py", "matlab": ".m", "octave": ".m"}.get(engine)
    if suffix is None or not original_script.is_file() or original_script.suffix.casefold() != suffix:
        raise ContractError("红队脚本扩展名与执行引擎不一致")
    if original_script.stat().st_size == 0:
        raise ContractError("红队证据脚本不能为空")
    clean_names: list[str] = []
    for value in output_paths:
        candidate = Path(value)
        if not value or candidate.is_absolute() or ".." in candidate.parts:
            raise ContractError("红队输出必须是 outputs/ 下的相对文件名")
        clean_names.append(candidate.as_posix())
    if not clean_names or len(set(clean_names)) != len(clean_names):
        raise ContractError("红队证据至少需要一个不重复输出")
    execution_dir = artifact_root / "executions" / evidence_id
    if execution_dir.exists():
        raise ContractError("红队 evidence_id 已存在，拒绝覆盖既有执行")
    execution_dir.mkdir(parents=True)
    scratch = execution_dir / "scratch"
    packet_dir = manifest_path.parent
    shutil.copytree(packet_dir, scratch / "packet")
    staged_script = scratch / f"script{suffix}"
    persistent_script = execution_dir / f"script{suffix}"
    shutil.copy2(original_script, staged_script)
    shutil.copy2(original_script, persistent_script)
    outputs_dir = scratch / "outputs"
    outputs_dir.mkdir()
    outputs = [outputs_dir / name for name in clean_names]
    command_path = _red_team_engine_command(root, engine)
    safe_arguments = [_safe_red_team_argument(value) for value in (arguments or [])]
    command = _red_team_command(engine, command_path, staged_script.name, safe_arguments)
    started_at = utc_now()
    environment = dict(os.environ)
    environment["SHUMOZIZI_REVIEW_PACKET"] = "packet"
    environment["SHUMOZIZI_REVIEW_OUTPUTS"] = "outputs"
    try:
        completed = subprocess.run(
            command,
            cwd=scratch,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
        exit_code, timed_out = completed.returncode, False
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code, timed_out = 124, True
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        ) + f"\n红队证据执行超过 {timeout_seconds} 秒，已终止。\n"
    stdout_path = execution_dir / "stdout.log"
    stderr_path = execution_dir / "stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr, encoding="utf-8", newline="\n")
    if exit_code != 0 or timed_out:
        raise ContractError(f"红队证据命令未成功完成（exit_code={exit_code}）")
    missing = [path for path in outputs if not path.is_file() or path.stat().st_size == 0]
    if missing:
        names = ", ".join(path.relative_to(outputs_dir).as_posix() for path in missing)
        raise ContractError("红队证据缺少非空输出: " + names)
    persistent_outputs = execution_dir / "outputs"
    shutil.copytree(outputs_dir, persistent_outputs)
    semantic_output: Path | None = None
    semantic_errors: list[str] = []
    for output in outputs:
        candidate = persistent_outputs / output.relative_to(outputs_dir)
        if candidate.suffix.casefold() != ".json":
            continue
        try:
            _require_red_team_semantic_output(kind, candidate)
        except ContractError as exc:
            semantic_errors.append(f"{candidate.name}: {exc}")
            continue
        semantic_output = candidate
        break
    if semantic_output is None:
        detail = "；".join(semantic_errors) or "没有 JSON 输出"
        raise ContractError("红队证据缺少合格的语义输出: " + detail)
    staged_packet = scratch / "packet"
    staged_inputs = _packet_input_files(staged_packet, manifest)
    receipt = {
        "schema_name": "red_team_evidence",
        "schema_version": "1.2",
        "run_id": root.name,
        "evidence_id": evidence_id,
        "kind": kind,
        "engine": engine,
        "packet": {
            "manifest_file": relative_inside(root, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
            "packet_tree_sha256": _packet_tree_hash(packet_dir, exclude_visualization_scripts=False),
        },
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "script": _file_evidence(root, persistent_script),
        "inputs": [_file_evidence(root, path) for path in staged_inputs],
        "outputs": [
            _file_evidence(root, persistent_outputs / path.relative_to(outputs_dir))
            for path in outputs
        ],
        "semantic_output": _file_evidence(root, semantic_output),
        "stdout": _file_evidence(root, stdout_path),
        "stderr": _file_evidence(root, stderr_path),
        "started_at": started_at,
        "finished_at": utc_now(),
    }
    _require_red_team_receipt(receipt)
    receipt_path = execution_dir / "receipt.json"
    atomic_json(receipt_path, receipt)
    return receipt


def _verify_file_evidence(run_dir: Path, evidence: dict[str, Any], *, require_nonempty: bool) -> Path:
    """重新计算一条冻结文件证据，防止审查结果跨文件变更复用。"""
    path = resolve_inside(run_dir, evidence["path"], must_exist=True)
    if sha256_file(path) != evidence["sha256"] or path.stat().st_size != evidence["size_bytes"]:
        raise ContractError(f"红队证据文件哈希或大小已变化: {evidence['path']}")
    if require_nonempty and path.stat().st_size == 0:
        raise ContractError(f"红队证据输出为空: {evidence['path']}")
    return path


def verify_red_team_artifacts(run_dir: Path) -> dict[str, Any]:
    """复验所有已冻结红队执行，返回可供导入摘要绑定的文件清单。"""
    root = run_dir.resolve()
    errors: list[str] = []
    receipts: list[dict[str, str]] = []
    evidence_files: dict[str, dict[str, str]] = {}
    evidence_kinds: set[str] = set()
    semantic_evidence: list[tuple[str, dict[str, Any]]] = []
    receipt_paths = sorted((_red_team_root(root) / "executions").glob("*/receipt.json"))
    if not receipt_paths:
        return {
            "valid": False,
            "errors": ["缺少 review/red_team_artifacts/ 下的实际执行证据"],
            "receipts": [],
            "files": {},
            "kinds": [],
            "semantic_evidence": [],
        }
    for receipt_path in receipt_paths:
        try:
            receipt = load_json(receipt_path)
            _require_red_team_receipt(receipt)
            if receipt["schema_version"] != "1.2":
                raise ContractError("旧版红队收据缺少科学语义输出，不能作为当前生产放行依据")
            if receipt["run_id"] != root.name:
                raise ContractError("红队证据收据 run_id 不匹配")
            execution_dir = receipt_path.parent.resolve()
            packet = receipt["packet"]
            packet_status = verify_review_packet(root, packet["manifest_file"])
            if not packet_status["success"]:
                raise ContractError("红队绑定的 scientific 审查包已失效: " + "；".join(packet_status["errors"]))
            manifest_path, manifest = _read_packet_manifest(root, packet["manifest_file"])
            if manifest["packet_kind"] != "scientific":
                raise ContractError("红队证据未绑定 scientific 审查包")
            if packet["manifest_sha256"] != sha256_file(manifest_path):
                raise ContractError("红队证据审查包清单哈希已变化")
            if packet["packet_tree_sha256"] != _packet_tree_hash(
                manifest_path.parent, exclude_visualization_scripts=False
            ):
                raise ContractError("红队证据审查包快照已变化")
            relative_receipt = relative_inside(root, receipt_path).as_posix()
            receipts.append({"path": relative_receipt, "sha256": sha256_file(receipt_path)})
            script = _verify_file_evidence(root, receipt["script"], require_nonempty=True)
            if execution_dir not in script.parents:
                raise ContractError("红队证据脚本不在对应清洁执行目录")
            if script.suffix.casefold() != {"python": ".py", "matlab": ".m", "octave": ".m"}[receipt["engine"]]:
                raise ContractError("红队脚本与收据引擎不一致")
            if not any(script.name in part for part in receipt["command"]):
                raise ContractError("红队证据命令未绑定登记脚本")
            for item in receipt["inputs"]:
                input_path = _verify_file_evidence(root, item, require_nonempty=False)
                staged_packet = execution_dir / "scratch" / "packet"
                if staged_packet not in input_path.parents:
                    raise ContractError("红队证据读取了冻结 packet 以外的输入")
            for item in receipt["outputs"]:
                output = _verify_file_evidence(root, item, require_nonempty=True)
                if execution_dir / "outputs" not in output.parents:
                    raise ContractError("红队证据输出不在对应清洁执行目录")
            semantic_output = _verify_file_evidence(
                root, receipt["semantic_output"], require_nonempty=True
            )
            if execution_dir / "outputs" not in semantic_output.parents:
                raise ContractError("红队语义输出不在对应清洁执行目录")
            if not any(
                item["path"] == receipt["semantic_output"]["path"]
                for item in receipt["outputs"]
            ):
                raise ContractError("红队语义输出未列入登记输出")
            evidence = _require_red_team_semantic_output(receipt["kind"], semantic_output)
            semantic_evidence.append((receipt["kind"], evidence))
            for item in (
                receipt["script"],
                *receipt["inputs"],
                *receipt["outputs"],
                receipt["stdout"],
                receipt["stderr"],
            ):
                path = _verify_file_evidence(root, item, require_nonempty=False)
                evidence_files[relative_inside(root, path).as_posix()] = {
                    "path": relative_inside(root, path).as_posix(),
                    "sha256": sha256_file(path),
                }
            evidence_kinds.add(receipt["kind"])
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{receipt_path.name}: {exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "receipts": receipts,
        "files": evidence_files,
        "kinds": sorted(evidence_kinds),
        "semantic_evidence": semantic_evidence,
    }


def _verified_evidence_assessment(run_dir: Path) -> dict[str, Any]:
    """复验执行收据并聚合其科学结论。"""
    verification = verify_red_team_artifacts(run_dir)
    if not verification["valid"]:
        raise ContractError("红队执行证据无效: " + "；".join(verification["errors"]))
    return _summarize_evidence_verdicts(verification["semantic_evidence"])


def _bind_red_team_artifacts(run_dir: Path, report: dict[str, str]) -> dict[str, Any]:
    """将报告引用与真实执行证据绑定，避免自由文本自证科学正确性。"""
    verification = verify_red_team_artifacts(run_dir)
    if not verification["valid"]:
        raise ContractError("红队执行证据无效: " + "；".join(verification["errors"]))
    report_path = _safe_run_path(run_dir, report["file"])
    content = report_path.read_text(encoding="utf-8")
    citations: list[dict[str, str]] = []
    for match in _REPORT_ARTIFACT_PATH.finditer(content):
        relative = match.group(0).replace("\\", "/").rstrip(".,;:!?")
        if relative not in verification["files"]:
            raise ContractError(f"审查报告引用了不存在或未执行的红队证据: {relative}")
        citations.append(verification["files"][relative])
    unique = {item["path"]: item for item in citations}
    if not unique:
        raise ContractError("科学审查报告必须引用至少一个 review/red_team_artifacts/ 的真实输出")
    output_paths = {
        item["path"]
        for receipt_path in verification["receipts"]
        for item in load_json(_safe_run_path(run_dir, receipt_path["path"]))["outputs"]
    }
    if not set(unique) & output_paths:
        raise ContractError("科学审查报告必须引用至少一个实际红队输出，而非只引用脚本")
    return {
        "receipts": verification["receipts"],
        "report_citations": list(unique.values()),
        "evidence_kinds": verification["kinds"],
    }


def _safe_run_path(run_dir: Path, relative: str, *, must_exist: bool = True) -> Path:
    """解析运行目录内文件，并统一返回其规范相对路径。"""
    return resolve_inside(run_dir, relative, must_exist=must_exist)


def _safe_packet_path(packet_dir: Path, relative: str, *, must_exist: bool = False) -> Path:
    """解析冻结包内路径，拒绝清单将检查目标导向包外。

    Args:
        packet_dir: 冻结审查包根目录。
        relative: 清单内的相对路径。
        must_exist: 是否要求目标已存在。

    Returns:
        位于审查包内的规范路径。

    Raises:
        ContractError: 路径为空、绝对路径、越过审查包边界或缺失。
    """
    candidate_input = Path(relative)
    if candidate_input.is_absolute() or not relative.strip():
        raise ContractError(f"审查包路径必须为非空相对路径: {relative}")
    root = packet_dir.resolve()
    candidate = (root / candidate_input).resolve()
    if candidate != root and root not in candidate.parents:
        raise ContractError(f"审查包路径越界: {relative}")
    if must_exist and not candidate.exists():
        raise ContractError(f"审查包文件不存在: {relative}")
    return candidate


def _source_root(run_dir: Path, relative: str) -> Path | None:
    """读取允许进入审查包的运行内目录或文件。"""
    candidate = (run_dir.resolve() / relative).resolve()
    if candidate != run_dir.resolve() and run_dir.resolve() not in candidate.parents:
        raise ContractError(f"审查包源路径越界: {relative}")
    return candidate if candidate.exists() else None


def _packet_files(
    source: Path,
    *,
    exclude_visualization_scripts: bool,
    exclude_quality_labels: bool = False,
) -> list[Path]:
    """返回需要冻结的文件，允许科学审查排除后续阶段的纯绘图脚本和质量标签。

    Args:
        exclude_visualization_scripts: 排除 figures/ 目录下的纯绘图脚本。
        exclude_quality_labels: 排除文件名含质量标签的文件（用于科学包去标签化）。
    """
    if source.is_file():
        if exclude_quality_labels and _packet_should_exclude(source):
            return []
        return [source]
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if exclude_quality_labels:
        files = [path for path in files if not _packet_should_exclude(path)]
    if not exclude_visualization_scripts:
        return files
    return [
        path
        for path in files
        if not path.relative_to(source).is_relative_to(_VISUALIZATION_CODE_DIRECTORY)
    ]


def _packet_tree_hash(
    source: Path,
    *,
    exclude_visualization_scripts: bool,
    exclude_quality_labels: bool = False,
) -> str:
    """计算审查快照的内容哈希，保证源树与冻结副本使用相同过滤规则。"""
    digest = hashlib.sha256()
    for item in _packet_files(
        source,
        exclude_visualization_scripts=exclude_visualization_scripts,
        exclude_quality_labels=exclude_quality_labels,
    ):
        relative = item.name if source.is_file() else item.relative_to(source).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def _packet_identifier(kind: str, state_revision: int) -> str:
    """生成不会覆盖历史审查证据的审查包标识。"""
    stamp = utc_now().replace("-", "").replace(":", "").replace("+", "").replace("Z", "Z")
    return f"{kind}-r{state_revision}-{stamp}"


def materialize_submission_package(run_dir: Path) -> dict[str, Any]:
    """物化评委实际可见的 PDF 与题定提交文件。

    ``problem/attachments`` 保存只读原始附件，其中可能包含空白结果模板；真正
    填写后的文件必须由求解阶段写入 ``artifacts/``，再由本函数复制到标准提交
    目录。这样盲审不会把空模板误当成最终答案。

    Args:
        run_dir: 当前 v3 运行目录。

    Returns:
        写入 ``paper/submission/manifest.json`` 的提交清单。

    Raises:
        ContractError: PDF 缺失、产物为空或提交目录含未登记文件。
    """
    root = run_dir.resolve()
    pdf = root / "paper" / "final.pdf"
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise ContractError("标准提交包需要非空 paper/final.pdf")
    submission_dir = root / "paper" / "submission"
    submission_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = submission_dir / "manifest.json"
    previous_files: set[str] = set()
    previous: dict[str, Any] | None = None
    if manifest_path.is_file():
        previous = load_json(manifest_path)
        if not isinstance(previous, dict) or previous.get("schema_version") != "1.0":
            raise ContractError("paper/submission 含未知提交清单，拒绝覆盖")
        previous_files = {
            item["submission"]
            for item in previous.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("submission"), str)
        }
    existing = {
        path.relative_to(submission_dir).as_posix()
        for path in submission_dir.rglob("*")
        if path.is_file() and path != manifest_path
    }
    unmanaged = existing - previous_files
    if unmanaged:
        raise ContractError(
            "paper/submission 含未登记文件，不能猜测其提交角色: "
            + ", ".join(sorted(unmanaged))
        )

    sources: list[tuple[Path, str, str]] = [(pdf, "final.pdf", "final_pdf")]
    artifacts_dir = root / "artifacts"
    attachment_names = {
        path.name.casefold()
        for path in (root / "problem" / "attachments").rglob("*")
        if path.is_file()
    }
    if artifacts_dir.is_dir():
        for source in sorted(path for path in artifacts_dir.rglob("*") if path.is_file()):
            if source.stat().st_size == 0:
                raise ContractError(
                    "标准提交包拒绝空产物: " + relative_inside(root, source).as_posix()
                )
            relative = source.relative_to(artifacts_dir).as_posix()
            role = (
                "completed_problem_attachment"
                if source.name.casefold() in attachment_names
                else "submission_attachment"
            )
            sources.append((source, f"attachments/{relative}", role))

    expected_files = [
        {
            "source": relative_inside(root, source).as_posix(),
            "submission": destination,
            "role": role,
            "sha256": sha256_file(source),
        }
        for source, destination, role in sources
    ]
    if previous is not None and previous.get("files") == expected_files:
        destinations_current = all(
            (submission_dir / item["submission"]).is_file()
            and sha256_file(submission_dir / item["submission"]) == item["sha256"]
            for item in expected_files
        )
        if destinations_current:
            return previous

    current_destinations = {destination for _, destination, _ in sources}
    for stale in previous_files - current_destinations:
        stale_path = _safe_packet_path(submission_dir, stale, must_exist=False)
        if stale_path.is_file():
            stale_path.unlink()

    files: list[dict[str, str]] = []
    for source, destination_relative, role in sources:
        destination = _safe_packet_path(
            submission_dir, destination_relative, must_exist=False
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append(
            {
                "source": relative_inside(root, source).as_posix(),
                "submission": destination_relative,
                "role": role,
                "sha256": sha256_file(destination),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "run_id": root.name,
        "files": files,
        "created_at": utc_now(),
    }
    atomic_json(manifest_path, manifest)
    return manifest


def _copy_packet_tree(
    run_dir: Path,
    packet_dir: Path,
    source_relative: str,
    destination_relative: str,
    *,
    exclude_quality_labels: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """复制一个审查允许的源树，并记录原始与副本的逐文件哈希。

    Args:
        exclude_quality_labels: 同时过滤文件名和哈希计算中的质量标签文件，
            确保源树哈希和副本树哈希使用同一个过滤后的文件集合。
            仅对 results/raw 源启用，不会误过滤 problem/code 中的合法文件。
    """
    source = _source_root(run_dir, source_relative)
    if source is None:
        return None, []
    # 只对候选结果目录应用标签过滤，不禁用 problem/code 中的 best/final 等正常文件名
    filter_labels = exclude_quality_labels and _source_is_candidate_results(source_relative)
    destination = packet_dir / destination_relative
    copied: list[dict[str, str]] = []
    exclude_visualization_scripts = source_relative == "code"
    if source.is_file():
        if filter_labels and _packet_should_exclude(source):
            return {"source": relative_inside(run_dir, source).as_posix(),
                    "packet": destination_relative, "sha256": ""}, []
        destination.parent.mkdir(parents=True, exist_ok=True)
        if filter_labels and source.suffix.lower() == ".json":
            _neutralize_candidate_json(source, destination)
            copied_hash = sha256_file(destination)  # 副本哈希（中性化后内容）
        else:
            shutil.copy2(source, destination)
            copied_hash = sha256_file(source)  # 源文件哈希（内容未变）
        copied.append(
            {
                "source": relative_inside(run_dir, source).as_posix(),
                "packet": destination.relative_to(packet_dir).as_posix(),
                "sha256": copied_hash,
            }
        )
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for item in _packet_files(
            source,
            exclude_visualization_scripts=exclude_visualization_scripts,
            exclude_quality_labels=filter_labels,
        ):
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if filter_labels and item.suffix.lower() == ".json":
                _neutralize_candidate_json(item, target)
                copied_hash = sha256_file(target)
            else:
                shutil.copy2(item, target)
                copied_hash = sha256_file(item)
            copied.append(
                {
                    "source": relative_inside(run_dir, item).as_posix(),
                    "packet": target.relative_to(packet_dir).as_posix(),
                    "sha256": copied_hash,
                }
            )
    # 哈希必须使用过滤后的同一视图（和 _packet_files 使用的 exclude_quality_labels 一致）
    # 对已复制的包目录计算哈希，而非源目录——中性化会改变 JSON 内容
    packet_source = packet_dir / destination_relative
    return {
        "source": relative_inside(run_dir, source).as_posix(),
        "packet": destination_relative,
        "sha256": _packet_tree_hash(
            packet_source if packet_source.exists() else source,
            exclude_visualization_scripts=exclude_visualization_scripts,
            exclude_quality_labels=False,  # 包目录已过滤+中性化，不再重复过滤
        ),
    }, copied


def build_review_packet(run_dir: Path, *, kind: str) -> dict[str, Any]:
    """冻结供独立对话阅读的无质量标签审查包。

    Args:
        run_dir: 当前 v3 运行目录。
        kind: ``objective-semantics``、``scientific``、``paper-blind`` 或 ``final-audit``。

    Returns:
        已写入的包清单。

    Raises:
        ContractError: 阶段、包类别或所需 PDF 不满足流程边界。
    """
    if kind not in _PACKET_ROOTS:
        raise ContractError(
            "审查包类别必须为 objective-semantics、scientific、paper-blind 或 final-audit"
        )
    state = read_simple_state(run_dir)
    required_phase = {
        "objective-semantics": "analysis",
        "scientific": "scientific_review",
        "paper-blind": "paper_review",
        "final-audit": "final_review",
    }[kind]
    if state["phase"] != required_phase:
        raise ContractError(f"{kind} 审查包只能在 {required_phase} 阶段创建")
    if kind in {"paper-blind", "final-audit"} and not (
        run_dir / "paper" / "final.pdf"
    ).is_file():
        raise ContractError(f"{kind} 审查包需要已编译的 paper/final.pdf")
    if kind in {"paper-blind", "final-audit"}:
        materialize_submission_package(run_dir)
    if kind == "final-audit":
        require_final_review_allowed(run_dir)

    missing_roots = [
        relative
        for relative in sorted(_REQUIRED_PACKET_ROOTS[kind])
        if _source_root(run_dir, relative) is None
    ]
    if missing_roots:
        raise ContractError("审查包缺少必需输入根: " + ", ".join(missing_roots))

    packet_id = _packet_identifier(kind, state["revision"])
    packet_dir = run_dir / REVIEW_ROOT / "packet" / kind / packet_id
    packet_dir.mkdir(parents=True, exist_ok=False)
    roots: list[dict[str, Any]] = []
    files: list[dict[str, str]] = []
    for source_relative in _PACKET_ROOTS[kind]:
        root, copied = _copy_packet_tree(
            run_dir,
            packet_dir,
            source_relative,
            _PACKET_DESTINATIONS[source_relative],
            exclude_quality_labels=(kind == "scientific"),
        )
        if root is not None:
            roots.append(root)
            files.extend(copied)
    manifest = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "packet_kind": kind,
        "packet_id": packet_id,
        "source_roots": roots,
        "files": files,
        "created_at": utc_now(),
    }
    atomic_json(packet_dir / "manifest.json", manifest)
    return manifest


def _read_packet_manifest(run_dir: Path, manifest_relative: str) -> tuple[Path, dict[str, Any]]:
    """读取并做最小结构检查的冻结审查包清单。"""
    manifest_path = _safe_run_path(run_dir, manifest_relative)
    payload = load_json(manifest_path)
    if not isinstance(payload, dict):
        raise ContractError("审查包 manifest 必须是对象")
    expected = {
        "schema_version",
        "run_id",
        "packet_kind",
        "packet_id",
        "source_roots",
        "files",
        "created_at",
    }
    if set(payload) != expected or payload["schema_version"] != "1.0":
        raise ContractError("审查包 manifest 格式不兼容")
    if payload["run_id"] != run_dir.name:
        raise ContractError("审查包 run_id 不匹配")
    if payload["packet_kind"] not in _PACKET_ROOTS:
        raise ContractError("审查包类别不合法")
    if not isinstance(payload["source_roots"], list) or not isinstance(payload["files"], list):
        raise ContractError("审查包缺少源树或文件清单")
    packet_id = payload["packet_id"]
    if not isinstance(packet_id, str) or not packet_id:
        raise ContractError("审查包 packet_id 不合法")
    packet_dir = _safe_run_path(
        run_dir,
        (REVIEW_ROOT / "packet" / payload["packet_kind"] / packet_id).as_posix(),
        must_exist=False,
    )
    if manifest_path != packet_dir / "manifest.json":
        raise ContractError("审查包 manifest 不在声明的冻结目录")

    roots_by_source: dict[str, dict[str, Any]] = {}
    for root in payload["source_roots"]:
        if not isinstance(root, dict) or set(root) != {"source", "packet", "sha256"}:
            raise ContractError("审查包源树条目格式不合法")
        source = root["source"]
        packet = root["packet"]
        digest = root["sha256"]
        if (
            not isinstance(source, str)
            or source not in _PACKET_ROOTS[payload["packet_kind"]]
            or not isinstance(packet, str)
            or packet != _PACKET_DESTINATIONS[source]
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ContractError("审查包源树条目包含未允许的路径或哈希")
        _safe_packet_path(packet_dir, packet)
        if source in roots_by_source:
            raise ContractError("审查包源树重复")
        roots_by_source[source] = root
    missing_roots = _REQUIRED_PACKET_ROOTS[payload["packet_kind"]] - set(roots_by_source)
    if missing_roots:
        raise ContractError("审查包缺少必要源树: " + ", ".join(sorted(missing_roots)))

    for item in payload["files"]:
        if not isinstance(item, dict) or set(item) != {"source", "packet", "sha256"}:
            raise ContractError("审查包文件条目格式不合法")
        source = item["source"]
        packet = item["packet"]
        digest = item["sha256"]
        if not all(isinstance(value, str) and value for value in (source, packet, digest)):
            raise ContractError("审查包文件条目缺少路径或哈希")
        if len(digest) != 64:
            raise ContractError("审查包文件哈希格式不合法")
        matching_roots = [
            root
            for root_source, root in roots_by_source.items()
            if source == root_source or source.startswith(f"{root_source}/")
        ]
        if not matching_roots:
            raise ContractError("审查包文件源路径不属于允许源树")
        if not any(
            packet == str(root["packet"]) or packet.startswith(f"{root['packet']}/")
            for root in matching_roots
        ):
            raise ContractError("审查包文件路径不属于对应冻结源树")
        _safe_packet_path(packet_dir, packet)
    return manifest_path, payload


def verify_review_packet(run_dir: Path, manifest_relative: str) -> dict[str, Any]:
    """验证审查包及其原始输入没有在审查后漂移。

    对科学审查包的 results/raw 源使用与构建时相同的过滤视图计算哈希，
    确保验证不因质量标签文件被排除而产生假阳性。
    """
    try:
        manifest_path, manifest = _read_packet_manifest(run_dir, manifest_relative)
        errors: list[str] = []
        packet_dir = manifest_path.parent
        is_scientific = manifest.get("packet_kind") == "scientific"
        for root in manifest["source_roots"]:
            if not isinstance(root, dict):
                errors.append("审查包源树条目不是对象")
                continue
            source_relative = root.get("source")
            packet_relative = root.get("packet")
            expected_hash = root.get("sha256")
            if not all(
                isinstance(item, str) and item
                for item in (source_relative, packet_relative, expected_hash)
            ):
                errors.append("审查包源树条目缺少路径或哈希")
                continue
            source = _source_root(run_dir, source_relative)
            packet_source = _safe_packet_path(packet_dir, packet_relative)
            # 验证时使用包副本哈希（构建时已记录中性化后的哈希）
            if source is None:
                errors.append(f"原始审查输入已缺失: {source_relative}")
            if not packet_source.exists() or _packet_tree_hash(
                packet_source,
                exclude_visualization_scripts=source_relative == "code",
                exclude_quality_labels=False,
            ) != expected_hash:
                errors.append(f"冻结审查副本已变化: {packet_relative}")
        # ── 逐文件验证：包文件哈希匹配；对于非中性化的源文件也检查源 ──
        for item in manifest["files"]:
            if not isinstance(item, dict):
                errors.append("审查包文件条目不是对象")
                continue
            source_relative = item.get("source", "")
            packet_relative = item.get("packet", "")
            expected_hash = item.get("sha256")
            if not all(isinstance(v, str) and v for v in (packet_relative, expected_hash)):
                errors.append("审查包文件条目缺少路径或哈希")
                continue
            try:
                packet_file = _safe_packet_path(packet_dir, packet_relative)
                if not packet_file.is_file():
                    errors.append(f"冻结审查文件缺失: {packet_relative}")
                    continue
                packet_hash = sha256_file(packet_file)
                if packet_hash != expected_hash:
                    errors.append(f"冻结审查文件已变化: {packet_relative}")
                # 非 candidate_results 源文件必须仍匹配（未中性化）
                if source_relative and not _source_is_candidate_results(
                    _infer_source_root(source_relative)
                ):
                    source = _safe_run_path(run_dir, source_relative)
                    if source.is_file() and sha256_file(source) != expected_hash:
                        errors.append(f"原始审查文件已变化: {source_relative}")
            except ContractError as exc:
                errors.append(str(exc))
        if not manifest["files"]:
            errors.append("审查包文件清单为空")
        return {
            "success": not errors,
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
            "errors": errors,
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"success": False, "errors": [str(exc)]}


def objective_semantics_review_required(run_dir: Path) -> bool:
    """判断当前生产运行是否具有需要独立解释的正式题面。"""
    state = read_simple_state(run_dir)
    return bool(
        state.get("execution_mode") == "production"
        and state.get("artifacts", {}).get("statement")
    )


# ── 聚合语义冲突对：在这两组中任取一对都会导致不同的优化方向与最终答案 ──
_SEMANTIC_CONFLICT_PAIRS: tuple[tuple[str, str], ...] = (
    ("sum_per_entity", "intersection_all"),
    ("sum_per_entity", "union_any"),
    ("multiobjective", "intersection_all"),
    ("multiobjective", "sum_per_entity"),
)


def _derive_semantic_conflict_fields(question: dict[str, Any]) -> dict[str, Any]:
    """从结构化 interpretations 推导语义冲突，不依赖自填的 selection_confidence。

    Returns:
        可合并回 question 的机器判定字段。
    """
    aggregations = sorted({
        item["aggregation"]
        for item in question["interpretations"]
    })
    distinct_count = len(aggregations)

    # 任一对冲突聚合 → changes_primary_result = true
    has_conflict = any(
        (a in aggregations and b in aggregations)
        for a, b in _SEMANTIC_CONFLICT_PAIRS
    )
    distinct = list(dict.fromkeys(aggregations))
    # language_evidence 必须绑定题面原文引用，不能只靠字段自报
    evidence_ref = question.get("language_evidence_ref", {})
    has_bound_evidence = (
        isinstance(evidence_ref, dict)
        and bool(evidence_ref.get("source_file", "").strip())
        and bool(evidence_ref.get("excerpt", "").strip())
    )
    language_resolves = (
        question.get("selection_basis") == "language_evidence" and has_bound_evidence
    )
    user_decision_required = (
        distinct_count >= 2
        and has_conflict
        and not language_resolves
    )
    return {
        "distinct_aggregations": distinct,
        "distinct_aggregation_count": distinct_count,
        "changes_primary_result": has_conflict,
        "changes_strategy": has_conflict,
        "language_uniquely_resolves": language_resolves,
        "user_decision_required": user_decision_required,
    }


def _validate_objective_assessment(
    run_dir: Path, payload: dict[str, Any]
) -> dict[str, Any]:
    """校验独立任务逐问给出的目标解释、备选聚合和选择依据。"""
    _validate_document(
        payload,
        "objective_semantics_assessment",
        "独立目标语义评估",
    )
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"]:
        raise ContractError("独立目标语义评估 run_id 不匹配")
    required_questions = list(state["required_questions"])
    if not required_questions:
        raise ContractError("目标语义预审前必须登记全部必答问题")
    question_ids = [item["question_id"] for item in payload["questions"]]
    if len(question_ids) != len(set(question_ids)):
        raise ContractError("独立目标语义评估包含重复问题")
    if set(question_ids) != set(required_questions):
        raise ContractError("独立目标语义评估必须逐一覆盖全部必答问题")
    for question in payload["questions"]:
        objective_ids = [item["objective_id"] for item in question["interpretations"]]
        if len(objective_ids) != len(set(objective_ids)):
            raise ContractError(f"{question['question_id']} 包含重复 objective_id")
        selected = question["selected_objective_id"]
        if selected not in objective_ids:
            raise ContractError(f"{question['question_id']} 的主目标不在候选解释中")
        diagnostics = set(question["diagnostic_objective_ids"])
        if not diagnostics.issubset(objective_ids):
            raise ContractError(f"{question['question_id']} 的诊断指标不在候选解释中")
        if selected in diagnostics:
            raise ContractError(f"{question['question_id']} 的主目标不能同时标为诊断指标")
        if question["selection_confidence"] == "ambiguous":
            if len(objective_ids) < 2 or not question["ambiguity_note"].strip():
                raise ContractError(f"{question['question_id']} 的歧义必须保留至少两个解释并说明原因")
            if question["selection_basis"] == "language_evidence":
                raise ContractError(
                    f"{question['question_id']} 仍有歧义时必须记录用户裁决或显式建模假设"
                )
        # 当 AI 声称 language_evidence 且存在语义冲突时，不能仅靠字段自报。
        # 必须有绑定的题面引用（源文件、页码/行号、原文、如何排除其他解释）。
        if question["selection_basis"] == "language_evidence":
            has_conflict = (
                len(question.get("distinct_aggregations", [])) >= 2
                or len(
                    {
                        item["aggregation"]
                        for item in question["interpretations"]
                    }
                )
                >= 2
            )
            if has_conflict:
                ref = question.get("language_evidence_ref", {})
                if not isinstance(ref, dict):
                    raise ContractError(
                        f"{question['question_id']} 的 language_evidence_ref 必须是对象"
                    )
                missing_parts = []
                if not ref.get("source_file", "").strip():
                    missing_parts.append("source_file")
                if not ref.get("excerpt", "").strip():
                    missing_parts.append("excerpt")
                if not ref.get("how_it_excludes_alternatives", "").strip():
                    missing_parts.append("how_it_excludes_alternatives")
                if missing_parts:
                    raise ContractError(
                        f"{question['question_id']} 的 language_evidence 必须绑定题面原文引用，"
                        f"缺少: {', '.join(missing_parts)}"
                    )
        if question["materiality"] == "high" and question["selection_confidence"] == "ambiguous":
            if question["selection_basis"] != "user_decision":
                raise ContractError(
                    f"{question['question_id']} 的高影响歧义必须由真实用户裁决，不能用建模假设自行放行"
                )
            if not question["human_confirmation_required"]:
                raise ContractError(f"{question['question_id']} 的高影响歧义必须要求人工确认")

        # ── 结构判定：当同一问题存在多个实质不同的聚合方式时，不能由 AI 自行填写
        # selection_confidence 绕过。必须按题面语言和聚合语义机器判定是否需要用户裁决。 ──
        machine = _derive_semantic_conflict_fields(question)
        question.update(machine)
        if machine["user_decision_required"]:
            if question["selection_basis"] != "user_decision":
                raise ContractError(
                    f"{question['question_id']} 存在 {machine['distinct_aggregation_count']} "
                    f"种实质不同的聚合语义（{', '.join(machine['distinct_aggregations'])}），"
                    f"会改变最终结果 ({machine['changes_primary_result']})，"
                    f"题面语言不能唯一排除 ({not machine['language_uniquely_resolves']})，"
                    f"必须由真实用户裁决，不能用 selection_confidence="
                    f"{question['selection_confidence']!r} 绕过"
                )
            if not question["human_confirmation_required"]:
                raise ContractError(
                    f"{question['question_id']} 的结构语义冲突要求 human_confirmation_required=true"
                )
    return payload


def _validate_question_reviews(
    run_dir: Path, question_reviews: list[dict[str, Any]] | None
) -> list[dict[str, Any]] | None:
    """校验逐问审查结论覆盖全部必答问题，且每个结论自洽。

    Returns:
        规范化后的逐问审查列表。

    Raises:
        ContractError: 生产模式下 question_reviews 为 None，或覆盖/自洽性不合法。
    """
    if question_reviews is None:
        # 兼容不含必答问题的运行（如纯探索、技能学习、无题面运行）
        state = read_simple_state(run_dir)
        if state.get("required_questions"):
            raise ContractError(
                "生产模式下逐问审查 (question_reviews) 必须覆盖全部必答问题，不能省略。"
            )
        return None
    if not isinstance(question_reviews, list):
        raise ContractError("question_reviews 必须是列表")
    state = read_simple_state(run_dir)
    required = set(state["required_questions"])
    covered = {item["question_id"] for item in question_reviews}
    if covered != required:
        missing = required - covered
        extra = covered - required
        parts = []
        if missing:
            parts.append("缺少必答问题: " + ", ".join(sorted(missing)))
        if extra:
            parts.append("含非必答问题: " + ", ".join(sorted(extra)))
        raise ContractError("逐问审查必须覆盖全部必答问题且不引入无关问题: " + "; ".join(parts))
    for item in question_reviews:
        if item["verdict"] not in _VERDICTS:
            raise ContractError(f"{item['question_id']} verdict 不合法: {item['verdict']}")
        if item["competition_strength"] not in {"weak", "qualified", "strong", "unknown"}:
            raise ContractError(
                f"{item['question_id']} competition_strength 不合法: {item['competition_strength']}"
            )
    return [
        {
            "question_id": item["question_id"],
            "verdict": item["verdict"],
            "competition_strength": item["competition_strength"],
            "evidence_ids": list(dict.fromkeys(item.get("evidence_ids", []))),
            "blocking_findings": list(dict.fromkeys(item.get("blocking_findings", []))),
        }
        for item in question_reviews
    ]


def _selected_objectives_sha256(assessment: dict[str, Any]) -> str:
    """稳定绑定逐问主目标，避免只改选择字段却复用旧人工裁决。"""
    selected = {
        question["question_id"]: question["selected_objective_id"]
        for question in assessment["questions"]
    }
    return sha256_bytes(json_bytes(selected))


def _human_ambiguity_binding(run_dir: Path, assessment: dict[str, Any]) -> dict[str, str] | None:
    """核验高影响歧义的人工原话与目标选择逐项一致。

    触发条件现在包括两套机制：
    1. 自填的高影响 + 显式 ambiguous（原有逻辑，保留兼容）；
    2. 机器派生的语义冲突（user_decision_required=true），不再依赖 AI 自评。
    """
    required = {
        question["question_id"]: question["selected_objective_id"]
        for question in assessment["questions"]
        if (
            question["materiality"] == "high"
            and question["selection_confidence"] == "ambiguous"
        )
        or question.get("user_decision_required", False)
    }
    if not required:
        return None
    path = _safe_run_path(run_dir, AMBIGUITY_DECISIONS_PATH.as_posix())
    decisions = load_json(path)
    _validate_document(decisions, "ambiguity_decisions", "高影响歧义人工裁决")
    if decisions["run_id"] != run_dir.name:
        raise ContractError("高影响歧义人工裁决 run_id 不匹配")
    by_question = {item["question_id"]: item for item in decisions["decisions"]}
    missing = sorted(set(required) - set(by_question))
    if missing:
        raise ContractError("高影响歧义缺少人工裁决: " + ", ".join(missing))
    mismatched = sorted(
        question_id
        for question_id, selected in required.items()
        if by_question[question_id]["selected_objective_id"] != selected
    )
    if mismatched:
        raise ContractError("人工裁决与选定主目标不一致: " + ", ".join(mismatched))
    return {
        "file": relative_inside(run_dir, path).as_posix(),
        "sha256": sha256_file(path),
    }


def _bound_review_file(run_dir: Path, relative: Path, *, suffix: str) -> dict[str, str]:
    """将审查任务写入的运行内文件绑定为路径与哈希。"""
    path = _safe_run_path(run_dir, relative.as_posix())
    path_relative = relative_inside(run_dir, path)
    if (
        not path_relative.parts
        or path_relative.parts[0] != REVIEW_ROOT.name
        or path_relative.parts[1:2] == ("packet",)
        or path.suffix.lower() != suffix
    ):
        raise ContractError(f"独立审查文件必须位于 review/ 下且扩展名为 {suffix}")
    return {"file": path_relative.as_posix(), "sha256": sha256_file(path)}


def _stale_results_for_objective_change(
    run_dir: Path, new_objectives_sha256: str
) -> None:
    """目标语义变化后标记所有旧生产结果为 stale。

    不直接修改结果 JSON 内容（那可能触发额外的 Schema 校验），
    而是将未绑定新目标哈希的 current 结果标记为 superseded。
    同时将质量和图表标记为失效。
    """
    # 1. 结果索引
    try:
        index = read_result_index(run_dir)
    except (ContractError, OSError):
        return
    dirty = False
    for item in index["results"]:
        if item.get("execution_mode") != "production":
            continue
        if item.get("status") != "current":
            continue
        existing = item.get("objective_semantics_sha256")
        if existing and existing == new_objectives_sha256:
            continue
        item["status"] = "superseded"
        dirty = True
    if dirty:
        from shumozizi.core.io import atomic_json as _atomic

        _atomic(run_dir / "results" / "index.json", index)

    # 2. 质量文档：paper_allowed 强制回退
    quality_path = run_dir / "results" / "quality.json"
    if quality_path.is_file():
        try:
            q = load_json(quality_path)
            stale = False
            for item in q.get("assessments", []):
                if item.get("result_role") == "accepted":
                    item["result_role"] = "candidate"
                    item["paper_allowed"] = False
                    item.setdefault("reasons", []).append(
                        "objective_semantics_changed"
                    )
                    stale = True
            if stale:
                from shumozizi.core.io import atomic_json as _atomic

                _atomic(quality_path, q)
        except (OSError, ValueError):
            pass

    # 3. 图表索引：标记所有生产图为 stale
    fig_index_path = run_dir / "figures" / "index.json"
    if fig_index_path.is_file():
        try:
            fig_idx = load_json(fig_index_path)
            stale = False
            for item in fig_idx.get("figures", []):
                existing = item.get("objective_semantics_sha256")
                if not existing or existing != new_objectives_sha256:
                    item["status"] = "stale"
                    stale = True
            if stale:
                from shumozizi.core.io import atomic_json as _atomic

                _atomic(fig_index_path, fig_idx)
        except (OSError, ValueError):
            pass


def import_objective_semantics_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    assessment_file: Path = OBJECTIVE_SEMANTICS_ASSESSMENT_PATH,
    report_file: Path = OBJECTIVE_SEMANTICS_REPORT_PATH,
) -> dict[str, Any]:
    """绑定只读题面的独立目标语义预审，并冻结实验必须消费的主目标。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("目标语义预审 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("目标语义预审含 P0/P1 时不能导入为 pass")
    if read_simple_state(run_dir)["phase"] == "complete":
        raise ContractError("已完成运行不能覆盖目标语义预审；请新建修订运行")
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "objective-semantics":
        raise ContractError("目标语义预审必须绑定 objective-semantics 审查包")
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("目标语义预审包已失效: " + "；".join(packet["errors"]))
    assessment_path = _safe_run_path(run_dir, assessment_file.as_posix())
    assessment = load_json(assessment_path)
    if not isinstance(assessment, dict):
        raise ContractError("独立目标语义评估必须是 JSON 对象")
    _validate_objective_assessment(run_dir, assessment)
    # 将机器派生字段（distinct_aggregations 等）持久化回评估文件，
    # 让下游消费者无需重复推导即可统一读取语义冲突判定。
    atomic_json(assessment_path, assessment)
    if not reviewer_thread_id.strip():
        raise ContractError("目标语义预审必须记录新对话 thread_id")
    ambiguity_decisions = _human_ambiguity_binding(run_dir, assessment)
    receipt = {
        "schema_name": "objective_semantics_review",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "file": relative_inside(run_dir, manifest_path).as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "assessment": _bound_review_file(run_dir, assessment_file, suffix=".json"),
        "selected_objectives_sha256": _selected_objectives_sha256(assessment),
        "report": _review_report(run_dir, report_file),
        "reviewer": {"thread_id": reviewer_thread_id},
        "reviewed_at": utc_now(),
    }
    if ambiguity_decisions is not None:
        receipt["ambiguity_decisions"] = ambiguity_decisions
    _validate_document(receipt, "objective_semantics_review", "目标语义预审收据")
    atomic_json(run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH, receipt)
    summary_path = run_dir / SUMMARY_PATH
    if summary_path.is_file():
        # 目标函数或聚合口径一旦重审，旧实验、论文和终审结论都失去共同前提。
        summary = read_review_summary(run_dir)
        summary["scientific_review"]["verdict"] = "revoked"
        summary["paper_blind_review"] = None
        summary["final_audit"] = None
        summary["updated_at"] = utc_now()
        _require_summary(summary)
        atomic_json(summary_path, summary)
    # 使所有绑定旧目标语义的结果 stale，并标记质量/图/Excel 必须重跑。
    _stale_results_for_objective_change(run_dir, _selected_objectives_sha256(assessment))
    # 目标改变后状态强制回退到 analysis，不能在旧结果上直接产出论文。
    try:
        update_simple_state(run_dir, phase="analysis")
    except ContractError:
        pass  # 已完成运行不允许直接回退；由调用方负责新建修订运行。
    return receipt


def objective_semantics_review_status(run_dir: Path) -> dict[str, Any]:
    """复验题面、独立目标解释、选择结果和报告均未漂移。"""
    if not objective_semantics_review_required(run_dir):
        return {"allowed": True, "required": False, "reason": "当前运行没有登记正式题面"}
    try:
        receipt = load_json(run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH)
        if not isinstance(receipt, dict):
            raise ContractError("目标语义预审收据必须是 JSON 对象")
        _validate_document(receipt, "objective_semantics_review", "目标语义预审收据")
        if receipt["run_id"] != run_dir.name:
            raise ContractError("目标语义预审收据 run_id 不匹配")
        packet = verify_review_packet(run_dir, receipt["packet"]["file"])
        if not packet["success"]:
            raise ContractError("目标语义预审包已失效: " + "；".join(packet["errors"]))
        if packet["manifest_sha256"] != receipt["packet"]["sha256"]:
            raise ContractError("目标语义预审包清单哈希已变化")
        assessment_path = _safe_run_path(run_dir, receipt["assessment"]["file"])
        if sha256_file(assessment_path) != receipt["assessment"]["sha256"]:
            raise ContractError("目标语义评估已变化")
        assessment = load_json(assessment_path)
        if not isinstance(assessment, dict):
            raise ContractError("独立目标语义评估必须是 JSON 对象")
        _validate_objective_assessment(run_dir, assessment)
        if _selected_objectives_sha256(assessment) != receipt["selected_objectives_sha256"]:
            raise ContractError("逐问选定目标已变化")
        ambiguity_decisions = _human_ambiguity_binding(run_dir, assessment)
        if ambiguity_decisions != receipt.get("ambiguity_decisions"):
            raise ContractError("高影响歧义人工裁决已变化或缺失")
        report_path = _safe_run_path(run_dir, receipt["report"]["file"])
        if sha256_file(report_path) != receipt["report"]["sha256"]:
            raise ContractError("目标语义预审报告已变化")
        allowed = bool(
            receipt["verdict"] == "pass"
            and receipt["highest_severity"] not in {"P0", "P1"}
        )
        return {
            "allowed": allowed,
            "required": True,
            "review": receipt,
            "assessment": assessment,
            "reason": "" if allowed else "目标语义预审未通过",
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "required": True, "reason": str(exc)}


def require_objective_semantics_review(run_dir: Path) -> None:
    """要求实验前已有只读题面的独立目标语义结论。"""
    status = objective_semantics_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入能力路由：独立目标语义预审未通过或已失效: " + status["reason"])


def read_review_summary(run_dir: Path) -> dict[str, Any]:
    """读取当前独立审查摘要。"""
    payload = load_json(run_dir / SUMMARY_PATH)
    _require_summary(payload)
    if payload["run_id"] != run_dir.name:
        raise ContractError("审查摘要 run_id 不匹配")
    return payload


def _reviewer_scientific(thread_id: str) -> dict[str, Any]:
    """记录由协调层负责核验的新科学审查对话标识。"""
    if not thread_id.strip():
        raise ContractError("独立科学审查必须记录新对话 thread_id")
    return {"thread_id": thread_id}


def _reviewer_paper(thread_id: str) -> dict[str, Any]:
    """记录由协调层负责核验的独立 PDF 盲审对话标识。"""
    if not thread_id.strip():
        raise ContractError("独立盲审必须记录新对话 thread_id")
    return {"thread_id": thread_id}


def _reviewer_final(thread_id: str) -> dict[str, Any]:
    """记录最终交付审核使用的第三个独立对话标识。"""
    if not thread_id.strip():
        raise ContractError("最终交付审核必须记录新对话 thread_id")
    return {"thread_id": thread_id}


def _require_competition_strength_evidence(
    competition_strength: str,
    artifacts: dict[str, Any],
    evidence_assessment: dict[str, Any],
    run_dir: Path,
    semantics: dict[str, Any],
    question_reviews: list[dict[str, Any]] | None = None,
) -> None:
    """阻止 CLI 仅靠一个标签把科学结果抬成可竞赛提交。"""
    if competition_strength not in {"qualified", "strong"}:
        return
    kinds = set(artifacts.get("evidence_kinds", []))
    has_independent_check = bool(kinds & {"independent-recompute", "alternative-formula"})
    has_adversarial_check = bool(
        kinds & {"counterexample", "small-enumeration", "search-challenge", "property-test"}
    )
    if not has_independent_check or not has_adversarial_check:
        raise ContractError(
            "qualified/strong 需要至少一项独立复算或替代公式，且需要一项反例、枚举、挑战或性质测试的真实收据"
        )
    if not evidence_assessment["promotion_allowed"]:
        raise ContractError(
            "qualified/strong 与红队证据结论冲突: "
            + "；".join(evidence_assessment["promotion_blockers"])
        )
    route = require_capability_route(run_dir)
    if "geometry_kinematics" in route["problem_families"] and (
        "geometry-continuous-validation" not in kinds
    ):
        raise ContractError(
            "几何/运动题的 qualified/strong 需要 geometry-continuous-validation，"
            "随机内部采样不能替代连续边界证明"
        )
    # ── 逐问证据绑定：qualified/strong 的每个问题必须有独立证据 ──
    verification = verify_red_team_artifacts(run_dir)
    semantic_evidence = verification.get("semantic_evidence", [])
    if question_reviews is not None:
        evidence_by_question: dict[str, dict[str, set[str]]] = {}
        for kind, evidence in semantic_evidence:
            qid = evidence.get("question_id")
            if not qid:
                continue
            groups = evidence_by_question.setdefault(
                qid, {"independent": set(), "adversarial": set()}
            )
            if kind in {"independent-recompute", "alternative-formula"}:
                groups["independent"].add(kind)
            elif kind in {
                "counterexample", "small-enumeration", "search-challenge",
                "property-test", "action-activation-challenge",
                "fixed-action-utilization",
            }:
                groups["adversarial"].add(kind)
        for item in question_reviews:
            if item["competition_strength"] not in {"qualified", "strong"}:
                continue
            qid = item["question_id"]
            ev = evidence_by_question.get(qid, {})
            if not ev.get("independent"):
                raise ContractError(
                    f"{qid} 标记为 {item['competition_strength']}，"
                    f"但没有属于该问题的独立复算或替代公式证据——"
                    f"Q1 的独立验证不能替其他问题背书"
                )
            if not ev.get("adversarial"):
                raise ContractError(
                    f"{qid} 缺少属于自己的对抗性证据"
                    f"（搜索挑战/消融/性质测试），不能标记为 qualified/strong"
                )

    required_actions = {
        question["question_id"]: question["decision_space"]["allowed_action_count"]
        for question in semantics.get("assessment", {}).get("questions", [])
        if question.get("decision_space", {}).get("action_cardinality") == "variable"
    }
    if required_actions:
        verification = verify_red_team_artifacts(run_dir)
        action_evidence = {
            evidence["question_id"]: evidence
            for kind, evidence in verification.get("semantic_evidence", [])
            if kind == "action-activation-challenge"
        }
        missing = sorted(set(required_actions) - set(action_evidence))
        if missing:
            raise ContractError(
                "可变动作数量问题缺少 action-activation-challenge: "
                + ", ".join(missing)
            )
        mismatched = sorted(
            question_id
            for question_id, allowed_count in required_actions.items()
            if action_evidence[question_id]["allowed_action_count"] != allowed_count
        )
        if mismatched:
            raise ContractError(
                "动作激活挑战未覆盖题面声明的完整动作数量: "
                + ", ".join(mismatched)
            )
    # ── 固定多动作利用检查：删除每个必要动作，验证边际贡献是否正 ──
    required_fixed = {
        question["question_id"]: question["decision_space"]["allowed_action_count"]
        for question in semantics.get("assessment", {}).get("questions", [])
        if question.get("decision_space", {}).get("action_cardinality") == "fixed"
        and (question["decision_space"].get("allowed_action_count") or 0) >= 2
    }
    if required_fixed:
        verification = verify_red_team_artifacts(run_dir)
        fixed_evidence = {
            evidence["question_id"]: evidence
            for kind, evidence in verification.get("semantic_evidence", [])
            if kind == "fixed-action-utilization"
        }
        missing = sorted(set(required_fixed) - set(fixed_evidence))
        if missing:
            raise ContractError(
                "固定多动作问题缺少 fixed-action-utilization 消融证据: "
                + ", ".join(missing)
            )
        for question_id, required_count in required_fixed.items():
            evidence = fixed_evidence[question_id]
            gains = [float(item) for item in evidence.get("marginal_gains", [])]
            if len(gains) != required_count:
                raise ContractError(
                    f"{question_id} fixed-action-utilization 消融动作数 "
                    f"({len(gains)}) 与题面要求 ({required_count}) 不一致"
                )
            tolerance = float(evidence.get("tolerance", 1e-12))
            zero_gain = [i + 1 for i, g in enumerate(gains) if g <= tolerance]
            if evidence.get("all_required_actions_material") and zero_gain:
                raise ContractError(
                    f"{question_id} 声称 all_required_actions_material=true，"
                    f"但第 {zero_gain} 枚动作边际贡献 ≤ {tolerance}"
                )
            if zero_gain:
                raise ContractError(
                    f"{question_id} 第 {zero_gain} 枚动作边际贡献 ≤ {tolerance}，"
                    f"不能标记为 qualified/strong；需重搜或降级为 weak"
            )


def _review_report(run_dir: Path, relative: Path) -> dict[str, str]:
    """绑定非空自由文本审查报告，而不把其压缩为固定检查表。"""
    report = _safe_run_path(run_dir, relative.as_posix())
    report_relative = relative_inside(run_dir, report)
    if (
        not report_relative.parts
        or report_relative.parts[0] != REVIEW_ROOT.name
        or report_relative.parts[1:2] == ("packet",)
        or report.suffix.lower() != ".md"
    ):
        raise ContractError("独立审查报告必须是 review/ 下、审查包外的 Markdown 文件")
    if report.stat().st_size < 32:
        raise ContractError("独立审查报告过短，缺少可复现判断")
    return {"file": report_relative.as_posix(), "sha256": sha256_file(report)}


def import_scientific_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    competition_strength: str,
    full_rerun_required: bool,
    affected_questions: list[str],
    reviewer_thread_id: str,
    report_file: Path = SCIENTIFIC_REPORT_PATH,
    question_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """将新对话的自由科学审查报告绑定为可机读的放行摘要。

    Args:
        question_reviews: 逐问细化结论，每项至少包含 question_id / verdict /
            competition_strength。当运行有必答问题时必须提供，不可回退到全局值。
    """
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("科学审查 verdict 或严重性不合法")
    if competition_strength not in {"weak", "qualified", "strong", "unknown"}:
        raise ContractError("competition_strength 不合法")
    if verdict == "pass" and (highest_severity in {"P0", "P1"} or full_rerun_required):
        raise ContractError("P0/P1 或全量重跑要求不能导入为 pass")
    state = read_simple_state(run_dir)
    if state["phase"] != "scientific_review":
        raise ContractError("科学审查结论只能在 scientific_review 阶段导入")
    # 有必答问题时逐问审查不可省略
    if state.get("required_questions") and question_reviews is None:
        raise ContractError(
            "有必答问题时逐问审查 (question_reviews) 必须覆盖全部问题，不能省略"
        )
    semantics = objective_semantics_review_status(run_dir)
    if not semantics["allowed"]:
        raise ContractError("科学审查前的目标语义预审未通过或已失效: " + semantics["reason"])
    if semantics.get("required") and reviewer_thread_id == semantics["review"]["reviewer"]["thread_id"]:
        raise ContractError("科学红队必须使用不同于目标语义预审的新对话")
    _, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "scientific":
        raise ContractError("科学审查必须绑定 scientific 审查包")
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("科学审查包已失效: " + "；".join(packet["errors"]))
    report = _review_report(run_dir, report_file)
    artifacts = _bind_red_team_artifacts(run_dir, report)
    evidence_assessment = _verified_evidence_assessment(run_dir)
    if verdict == "pass" and not evidence_assessment["pass_allowed"]:
        raise ContractError(
            "科学审查 pass 与红队负面证据冲突: "
            + "；".join(evidence_assessment["blocking_reasons"])
        )
    # ── 逐问审查：校验并合并 per-question verdicts ──
    validated_question_reviews = _validate_question_reviews(
        run_dir, question_reviews
    )
    _require_competition_strength_evidence(
        competition_strength,
        artifacts,
        evidence_assessment,
        run_dir,
        semantics,
        validated_question_reviews,
    )
    semantics_binding = None
    if semantics.get("required"):
        semantics_receipt = run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH
        semantics_binding = {
            "file": relative_inside(run_dir, semantics_receipt).as_posix(),
            "sha256": sha256_file(semantics_receipt),
        }
    review = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "competition_strength": competition_strength,
        "full_rerun_required": full_rerun_required,
        "affected_questions": list(dict.fromkeys(affected_questions)),
        "packet": {
            "manifest_file": packet["manifest_file"],
            "manifest_sha256": packet["manifest_sha256"],
        },
        "report": report,
        "artifacts": artifacts,
        "objective_semantics": semantics_binding,
        "reviewer": _reviewer_scientific(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    if validated_question_reviews is not None:
        review["question_reviews"] = validated_question_reviews
    # 没有必答问题时仍用 v1.5 兼容旧运行
    summary_version = "1.6" if validated_question_reviews is not None else "1.5"
    summary = {
        "schema_version": summary_version,
        "run_id": run_dir.name,
        "scientific_review": review,
        # 新科学结论会改变论文可用性；旧盲审不能跨越该边界复用。
        "paper_blind_review": None,
        "final_audit": None,
        "updated_at": utc_now(),
    }
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def import_paper_blind_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    argumentation_complete: bool,
    readability_passed: bool,
    empty_sections: list[str] | None = None,
    unreadable_pages: list[int] | None = None,
    report_file: Path = PAPER_BLIND_REPORT_PATH,
) -> dict[str, Any]:
    """绑定独立盲审报告；它只决定提交可读性，不替代科学红队。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("盲审 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("盲审含 P0/P1 时不能导入为 pass")
    empty_sections = list(dict.fromkeys(empty_sections or []))
    unreadable_pages = list(dict.fromkeys(unreadable_pages or []))
    if verdict == "pass" and (
        not argumentation_complete
        or not readability_passed
        or empty_sections
        or unreadable_pages
    ):
        raise ContractError("PDF 盲审未确认逐问论证完整和页面可读时不能导入为 pass")
    if read_simple_state(run_dir)["phase"] != "paper_review":
        raise ContractError("PDF 盲审结论只能在 paper_review 阶段导入")
    require_paper_generation_allowed(run_dir)
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("盲审包已失效: " + "；".join(packet["errors"]))
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "paper-blind":
        raise ContractError("盲审必须绑定 paper-blind 审查包")
    summary = read_review_summary(run_dir)
    used_threads = {summary["scientific_review"]["reviewer"]["thread_id"]}
    semantics = objective_semantics_review_status(run_dir)
    if semantics.get("required"):
        used_threads.add(semantics["review"]["reviewer"]["thread_id"])
    if reviewer_thread_id in used_threads:
        raise ContractError("PDF 盲审必须使用不同于科学红队、目标语义预审的新对话")
    summary["schema_version"] = "1.4"
    summary["paper_blind_review"] = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
        },
        "report": _review_report(run_dir, report_file),
        "assessment": {
            "argumentation_complete": argumentation_complete,
            "readability_passed": readability_passed,
            "empty_sections": empty_sections,
            "unreadable_pages": unreadable_pages,
        },
        "reviewer": _reviewer_paper(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    # 新 PDF 盲审会改变最终交付边界，旧终审不能复用。
    summary["final_audit"] = None
    summary["updated_at"] = utc_now()
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def import_final_audit(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    report_file: Path = FINAL_AUDIT_REPORT_PATH,
) -> dict[str, Any]:
    """绑定第三个新对话完成的最终交付审核报告。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("最终交付审核 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("最终交付审核含 P0/P1 时不能导入为 pass")
    if read_simple_state(run_dir)["phase"] != "final_review":
        raise ContractError("最终交付审核只能在 final_review 阶段导入")
    require_final_review_allowed(run_dir)
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("最终交付审核包已失效: " + "；".join(packet["errors"]))
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "final-audit":
        raise ContractError("最终交付审核必须绑定 final-audit 审查包")
    summary = read_review_summary(run_dir)
    used_threads = {
        summary["scientific_review"]["reviewer"]["thread_id"],
        summary["paper_blind_review"]["reviewer"]["thread_id"],
    }
    semantics = objective_semantics_review_status(run_dir)
    if semantics.get("required"):
        used_threads.add(semantics["review"]["reviewer"]["thread_id"])
    if reviewer_thread_id in used_threads:
        raise ContractError("最终交付审核必须使用不同于前两轮审核的第三个新对话")
    summary["schema_version"] = "1.4"
    summary["final_audit"] = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
        },
        "report": _review_report(run_dir, report_file),
        "reviewer": _reviewer_final(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    summary["updated_at"] = utc_now()
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def _review_current(
    run_dir: Path, review: dict[str, Any], *, expected_kind: str
) -> tuple[bool, str]:
    """确认摘要仍绑定同一份未漂移的冻结审查包与报告。"""
    _, manifest = _read_packet_manifest(run_dir, review["packet"]["manifest_file"])
    if manifest["packet_kind"] != expected_kind:
        return False, f"审查摘要绑定了 {manifest['packet_kind']} 审查包，而非 {expected_kind}"
    packet = verify_review_packet(run_dir, review["packet"]["manifest_file"])
    if not packet["success"]:
        return False, "；".join(packet["errors"])
    if packet["manifest_sha256"] != review["packet"]["manifest_sha256"]:
        return False, "审查包清单哈希已变化"
    report = _safe_run_path(run_dir, review["report"]["file"])
    if sha256_file(report) != review["report"]["sha256"]:
        return False, "审查报告哈希已变化"
    if expected_kind == "scientific":
        if "artifacts" not in review:
            return False, "科学审查缺少可执行红队证据；旧摘要不能作为生产放行依据"
        try:
            artifacts = _bind_red_team_artifacts(run_dir, review["report"])
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            return False, str(exc)
        if artifacts != review["artifacts"]:
            return False, "红队证据收据或报告引用已变化"
        evidence_assessment = _verified_evidence_assessment(run_dir)
        if not evidence_assessment["pass_allowed"]:
            return False, "红队出现负面科学证据: " + "；".join(
                evidence_assessment["blocking_reasons"]
            )
        semantics = objective_semantics_review_status(run_dir)
        binding = review.get("objective_semantics")
        if semantics.get("required"):
            receipt_path = run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH
            if not isinstance(binding, dict) or binding.get("sha256") != sha256_file(
                receipt_path
            ):
                return False, "科学审查绑定的目标语义版本已变化"
        elif binding is not None:
            return False, "科学审查绑定了当前运行不需要的目标语义收据"
    return True, ""


def scientific_review_status(run_dir: Path) -> dict[str, Any]:
    """返回科学红队是否仍可作为论文放行依据。

    当逐问审查 (question_reviews) 存在时，全部必答问题 verdict=pass 才允许放行，
    单问证据不能替其他问题背书。
    """
    try:
        semantics = objective_semantics_review_status(run_dir)
        if not semantics["allowed"]:
            return {
                "allowed": False,
                "submission_ready": False,
                "competition_strength": "unknown",
                "reason": "目标语义预审未通过或已失效: " + semantics["reason"],
            }
        summary = read_review_summary(run_dir)
        review = summary["scientific_review"]
        current, reason = _review_current(run_dir, review, expected_kind="scientific")
        evidence_assessment = _verified_evidence_assessment(run_dir) if current else None
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
            and not review["full_rerun_required"]
        )
        question_reviews = review.get("question_reviews")
        if question_reviews is not None and allowed:
            # 逐问模式下，任一必答问题非 pass 即阻断
            failed = [
                item["question_id"]
                for item in question_reviews
                if item["verdict"] != "pass"
            ]
            if failed:
                allowed = False
                reason = "逐问审查未全部通过: " + ", ".join(failed)
        submission_ready = bool(
            allowed
            and review["competition_strength"] in {"qualified", "strong"}
            and evidence_assessment is not None
            and evidence_assessment["promotion_allowed"]
        )
        if question_reviews is not None and submission_ready:
            # 逐问模式下任一问题 competition_strength 不达标 → 不可提交
            weak_questions = [
                item["question_id"]
                for item in question_reviews
                if item["competition_strength"] not in {"qualified", "strong"}
            ]
            if weak_questions:
                submission_ready = False
        return {
            "allowed": allowed,
            "submission_ready": submission_ready,
            "competition_strength": review["competition_strength"],
            "question_reviews": question_reviews,
            "review": review,
            "reason": reason,
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            "allowed": False,
            "submission_ready": False,
            "competition_strength": "unknown",
            "reason": str(exc),
        }


def require_paper_generation_allowed(run_dir: Path) -> None:
    """要求当前源代码、输入和候选结果已通过独立科学红队。"""
    status = scientific_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入论文阶段：独立科学红队未通过或已失效: " + status["reason"])


def paper_blind_review_status(run_dir: Path) -> dict[str, Any]:
    """返回盲审是否仍可作为提交前放行依据。"""
    try:
        scientific = scientific_review_status(run_dir)
        if not scientific["allowed"]:
            return {"allowed": False, "reason": "科学红队未通过或已失效"}
        summary = read_review_summary(run_dir)
        review = summary["paper_blind_review"]
        if review is None:
            return {"allowed": False, "reason": "缺少独立 PDF 盲审"}
        current, reason = _review_current(run_dir, review, expected_kind="paper-blind")
        assessment = review.get("assessment")
        assessment_passed = bool(
            assessment is None
            or (
                assessment["argumentation_complete"]
                and assessment["readability_passed"]
                and not assessment["empty_sections"]
                and not assessment["unreadable_pages"]
            )
        )
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
            and assessment_passed
        )
        return {"allowed": allowed, "review": review, "reason": reason}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def require_paper_blind_review_allowed(run_dir: Path) -> None:
    """要求当前 PDF 已经由新的盲审对话放行。"""
    status = paper_blind_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入机械终检：独立 PDF 盲审未通过或已失效: " + status["reason"])


def mechanical_qa_status(run_dir: Path) -> dict[str, Any]:
    """返回机械 QA 是否通过且仍绑定当前最终 PDF。

    机械 QA 必须由正式检查器生成，不接受手写 synthetic 单条检查。
    """
    try:
        mechanical = load_json(run_dir / "qa" / "mechanical-qa.json")
        pdf = run_dir / "paper" / "final.pdf"
        if (
            not isinstance(mechanical, dict)
            or mechanical.get("schema_version") != "1.0"
            or mechanical.get("run_id") != run_dir.name
            or mechanical.get("workflow") != "capability-first-v3"
            or mechanical.get("status") != "pass"
        ):
            return {"allowed": False, "reason": "机械 QA 未通过"}
        # 拒绝 synthetic 伪造：必须由真实检查器生成
        generator = mechanical.get("generator_id", "")
        if not generator or generator == "synthetic":
            return {"allowed": False, "reason": "机械 QA 必须由正式检查器生成，不接受手写伪造"}
        if not mechanical.get("generated_at"):
            return {"allowed": False, "reason": "机械 QA 缺少 generator_id 或 generated_at"}
        # 最低必要检查集合
        required_check_ids = {
            "pdf_exists", "pdf_hash", "anonymous", "placeholder_scan",
            "result_reference", "metric_consistency",
            "figure_readability", "submission_manifest",
        }
        checks = mechanical.get("checks")
        if not isinstance(checks, list) or any(
            not isinstance(check, dict) or check.get("passed") is not True for check in checks
        ):
            return {"allowed": False, "reason": "机械 QA 缺少全部通过的检查记录"}
        check_ids = {check.get("id", "") for check in checks}
        if "synthetic" in check_ids or not (check_ids & required_check_ids):
            return {
                "allowed": False,
                "reason": "机械 QA 缺少正式检查项，不能只含 synthetic 伪类",
            }
        if (
            mechanical.get("final_pdf") != "paper/final.pdf"
            or not pdf.is_file()
            or mechanical.get("final_pdf_sha256") != sha256_file(pdf)
        ):
            return {"allowed": False, "reason": "机械 QA 未绑定当前最终 PDF"}
        return {"allowed": True, "reason": "", "mechanical_qa": mechanical}
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": "机械 QA 无法读取: " + str(exc)}


def require_mechanical_qa_allowed(run_dir: Path) -> None:
    """要求当前 PDF 的机械 QA 已全部通过。"""
    status = mechanical_qa_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入最终交付审核：" + status["reason"])


def require_final_review_allowed(run_dir: Path) -> None:
    """要求前两轮独立审核和机械 QA 均仍绑定当前交付物。"""
    require_paper_blind_review_allowed(run_dir)
    require_mechanical_qa_allowed(run_dir)


def final_audit_status(run_dir: Path) -> dict[str, Any]:
    """返回第三轮最终交付审核是否仍可作为完成依据。"""
    try:
        require_final_review_allowed(run_dir)
        summary = read_review_summary(run_dir)
        review = summary.get("final_audit")
        if review is None:
            return {"allowed": False, "reason": "缺少独立最终交付审核"}
        current, reason = _review_current(run_dir, review, expected_kind="final-audit")
        reviewer_threads = {
            summary["scientific_review"]["reviewer"]["thread_id"],
            summary["paper_blind_review"]["reviewer"]["thread_id"],
            review["reviewer"]["thread_id"],
        }
        distinct_reviewers = len(reviewer_threads) == 3
        allowed = bool(
            current
            and distinct_reviewers
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
        )
        if current and not distinct_reviewers:
            reason = "三轮独立审核未使用三个不同对话"
        return {"allowed": allowed, "review": review, "reason": reason}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def competition_submission_status(run_dir: Path) -> dict[str, Any]:
    """区分科学可用与竞赛可提交，避免 weak 结果被标记为 complete。"""
    scientific = scientific_review_status(run_dir)
    if not scientific["allowed"]:
        return {
            "scientific_valid": False,
            "competition_strength": scientific.get("competition_strength", "unknown"),
            "submission_ready": False,
            "status": "scientific_review_unavailable",
            "reason": scientific["reason"],
        }
    strength = scientific["competition_strength"]
    if strength not in {"qualified", "strong"}:
        return {
            "scientific_valid": True,
            "competition_strength": strength,
            "submission_ready": False,
            "status": "scientifically_valid_but_not_competitive",
            "reason": f"科学结果可写成论文但竞争力为 {strength}，不能标记 complete",
        }
    return {
        "scientific_valid": True,
        "competition_strength": strength,
        "submission_ready": True,
        "status": "submission_ready",
        "reason": "",
    }


def completion_status(run_dir: Path) -> dict[str, Any]:
    """组合三轮独立审核与机械 QA，形成唯一的 complete 放行结论。"""
    review = final_audit_status(run_dir)
    if not review["allowed"]:
        return {"allowed": False, "reason": review["reason"]}
    competition = competition_submission_status(run_dir)
    if not competition["submission_ready"]:
        return {"allowed": False, **competition}
    return {
        "allowed": True,
        "reason": "",
        "scientific_valid": True,
        "competition_strength": competition["competition_strength"],
        "submission_ready": True,
        "status": "submission_ready",
    }


def require_completion_allowed(run_dir: Path) -> None:
    """要求三轮独立审查与机械 QA 同时通过，禁止仅凭 PDF 交付。"""
    status = completion_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能标记 complete：" + status["reason"])
