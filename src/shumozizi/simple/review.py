"""管理 v3 的冻结审查包与独立审查放行边界。"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.state import read_simple_state, utc_now

REVIEW_ROOT = Path("review")
SUMMARY_PATH = REVIEW_ROOT / "summary.json"
SCIENTIFIC_REPORT_PATH = REVIEW_ROOT / "SCIENTIFIC_RED_TEAM.md"
PAPER_BLIND_REPORT_PATH = REVIEW_ROOT / "PAPER_BLIND_REVIEW.md"
_PACKET_ROOTS = {
    "scientific": ("problem", "code", "results/raw"),
    "paper-blind": ("problem", "paper/final.pdf", "paper/submission"),
}
_PACKET_DESTINATIONS = {
    "problem": "problem",
    "code": "source_snapshot",
    "results/raw": "candidate_results",
    "paper/final.pdf": "paper/final.pdf",
    "paper/submission": "submission",
}
_REQUIRED_PACKET_ROOTS = {
    "scientific": frozenset(("problem", "code", "results/raw")),
    "paper-blind": frozenset(("problem", "paper/final.pdf")),
}
_SEVERITIES = {"none", "P0", "P1", "P2", "P3"}
_VERDICTS = {"pass", "fail", "needs_rework", "revoked"}
_VISUALIZATION_CODE_DIRECTORY = Path("figures")


def _schema() -> dict[str, Any]:
    """读取独立审查摘要的 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "simple_review_summary.schema.json")


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


def _packet_files(source: Path, *, exclude_visualization_scripts: bool) -> list[Path]:
    """返回需要冻结的文件，允许科学审查排除后续阶段的纯绘图脚本。"""
    if source.is_file():
        return [source]
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not exclude_visualization_scripts:
        return files
    return [
        path
        for path in files
        if not path.relative_to(source).is_relative_to(_VISUALIZATION_CODE_DIRECTORY)
    ]


def _packet_tree_hash(source: Path, *, exclude_visualization_scripts: bool) -> str:
    """计算审查快照的内容哈希，保证源树与冻结副本使用相同过滤规则。"""
    digest = hashlib.sha256()
    for item in _packet_files(
        source,
        exclude_visualization_scripts=exclude_visualization_scripts,
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


def _copy_packet_tree(
    run_dir: Path,
    packet_dir: Path,
    source_relative: str,
    destination_relative: str,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """复制一个审查允许的源树，并记录原始与副本的逐文件哈希。"""
    source = _source_root(run_dir, source_relative)
    if source is None:
        return None, []
    destination = packet_dir / destination_relative
    copied: list[dict[str, str]] = []
    exclude_visualization_scripts = source_relative == "code"
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(
            {
                "source": relative_inside(run_dir, source).as_posix(),
                "packet": destination.relative_to(packet_dir).as_posix(),
                "sha256": sha256_file(source),
            }
        )
    else:
        # 空目录也必须冻结为目录；否则刚创建的审查包会被误判为已漂移。
        destination.mkdir(parents=True, exist_ok=True)
        for item in _packet_files(
            source,
            exclude_visualization_scripts=exclude_visualization_scripts,
        ):
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied.append(
                {
                    "source": relative_inside(run_dir, item).as_posix(),
                    "packet": target.relative_to(packet_dir).as_posix(),
                    "sha256": sha256_file(item),
                }
            )
    return {
        "source": relative_inside(run_dir, source).as_posix(),
        "packet": destination_relative,
        "sha256": _packet_tree_hash(
            source,
            exclude_visualization_scripts=exclude_visualization_scripts,
        ),
    }, copied


def build_review_packet(run_dir: Path, *, kind: str) -> dict[str, Any]:
    """冻结供独立对话阅读的无质量标签审查包。

    Args:
        run_dir: 当前 v3 运行目录。
        kind: ``scientific`` 或 ``paper-blind``。

    Returns:
        已写入的包清单。

    Raises:
        ContractError: 阶段、包类别或所需 PDF 不满足流程边界。
    """
    if kind not in _PACKET_ROOTS:
        raise ContractError("审查包类别必须为 scientific 或 paper-blind")
    state = read_simple_state(run_dir)
    required_phase = "scientific_review" if kind == "scientific" else "paper_review"
    if state["phase"] != required_phase:
        raise ContractError(f"{kind} 审查包只能在 {required_phase} 阶段创建")
    if kind == "paper-blind" and not (run_dir / "paper" / "final.pdf").is_file():
        raise ContractError("盲审包需要已编译的 paper/final.pdf")

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
    """验证审查包及其原始输入没有在审查后漂移。"""
    try:
        manifest_path, manifest = _read_packet_manifest(run_dir, manifest_relative)
        errors: list[str] = []
        packet_dir = manifest_path.parent
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
            if source is None:
                errors.append(f"原始审查输入已缺失: {source_relative}")
            elif _packet_tree_hash(
                source,
                exclude_visualization_scripts=source_relative == "code",
            ) != expected_hash:
                errors.append(f"原始审查输入已变化: {source_relative}")
            if not packet_source.exists() or _packet_tree_hash(
                packet_source,
                exclude_visualization_scripts=source_relative == "code",
            ) != expected_hash:
                errors.append(f"冻结审查副本已变化: {packet_relative}")
        for item in manifest["files"]:
            if not isinstance(item, dict):
                errors.append("审查包文件条目不是对象")
                continue
            source_relative = item.get("source")
            packet_relative = item.get("packet")
            expected_hash = item.get("sha256")
            if not all(
                isinstance(value, str) and value
                for value in (source_relative, packet_relative, expected_hash)
            ):
                errors.append("审查包文件条目缺少路径或哈希")
                continue
            try:
                source = _safe_run_path(run_dir, source_relative)
                packet_file = _safe_packet_path(packet_dir, packet_relative)
                if sha256_file(source) != expected_hash:
                    errors.append(f"原始审查文件已变化: {source_relative}")
                if not packet_file.is_file() or sha256_file(packet_file) != expected_hash:
                    errors.append(f"冻结审查文件已变化: {packet_relative}")
            except ContractError as exc:
                errors.append(str(exc))
        return {
            "success": not errors,
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
            "errors": errors,
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"success": False, "errors": [str(exc)]}


def read_review_summary(run_dir: Path) -> dict[str, Any]:
    """读取当前独立审查摘要。"""
    payload = load_json(run_dir / SUMMARY_PATH)
    _require_summary(payload)
    if payload["run_id"] != run_dir.name:
        raise ContractError("审查摘要 run_id 不匹配")
    return payload


def _reviewer_scientific(thread_id: str) -> dict[str, Any]:
    """生成审查隔离声明，调用方只可提供新对话标识。"""
    if not thread_id.strip():
        raise ContractError("独立科学审查必须记录新对话 thread_id")
    return {
        "thread_id": thread_id,
        "fresh_context": True,
        "solver_context_visible": False,
        "previous_review_visible": False,
        "quality_verdicts_visible": False,
        "decision_log_visible_initially": False,
    }


def _reviewer_paper(thread_id: str) -> dict[str, Any]:
    """生成盲审隔离声明，禁止初始接触代码和已有结论。"""
    if not thread_id.strip():
        raise ContractError("独立盲审必须记录新对话 thread_id")
    return {
        "thread_id": thread_id,
        "fresh_context": True,
        "solver_context_visible": False,
        "scientific_review_visible": False,
        "quality_verdicts_visible": False,
        "code_visible_initially": False,
    }


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
) -> dict[str, Any]:
    """将新对话的自由科学审查报告绑定为可机读的放行摘要。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("科学审查 verdict 或严重性不合法")
    if competition_strength not in {"weak", "qualified", "strong", "unknown"}:
        raise ContractError("competition_strength 不合法")
    if verdict == "pass" and (highest_severity in {"P0", "P1"} or full_rerun_required):
        raise ContractError("P0/P1 或全量重跑要求不能导入为 pass")
    if read_simple_state(run_dir)["phase"] != "scientific_review":
        raise ContractError("科学审查结论只能在 scientific_review 阶段导入")
    _, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "scientific":
        raise ContractError("科学审查必须绑定 scientific 审查包")
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("科学审查包已失效: " + "；".join(packet["errors"]))
    summary = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "scientific_review": {
            "verdict": verdict,
            "highest_severity": highest_severity,
            "competition_strength": competition_strength,
            "full_rerun_required": full_rerun_required,
            "affected_questions": list(dict.fromkeys(affected_questions)),
            "packet": {
                "manifest_file": packet["manifest_file"],
                "manifest_sha256": packet["manifest_sha256"],
            },
            "report": _review_report(run_dir, report_file),
            "reviewer": _reviewer_scientific(reviewer_thread_id),
            "reviewed_at": utc_now(),
        },
        # 新科学结论会改变论文可用性；旧盲审不能跨越该边界复用。
        "paper_blind_review": None,
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
    report_file: Path = PAPER_BLIND_REPORT_PATH,
) -> dict[str, Any]:
    """绑定独立盲审报告；它只决定提交可读性，不替代科学红队。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("盲审 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("盲审含 P0/P1 时不能导入为 pass")
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
    if reviewer_thread_id == summary["scientific_review"]["reviewer"]["thread_id"]:
        raise ContractError("PDF 盲审必须使用不同于科学红队的新对话")
    summary["paper_blind_review"] = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
        },
        "report": _review_report(run_dir, report_file),
        "reviewer": _reviewer_paper(reviewer_thread_id),
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
    return True, ""


def scientific_review_status(run_dir: Path) -> dict[str, Any]:
    """返回科学红队是否仍可作为论文放行依据。"""
    try:
        summary = read_review_summary(run_dir)
        review = summary["scientific_review"]
        current, reason = _review_current(run_dir, review, expected_kind="scientific")
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
            and not review["full_rerun_required"]
        )
        return {"allowed": allowed, "review": review, "reason": reason}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


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
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
        )
        return {"allowed": allowed, "review": review, "reason": reason}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def require_paper_blind_review_allowed(run_dir: Path) -> None:
    """要求当前 PDF 已经由新的盲审对话放行。"""
    status = paper_blind_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入机械终检：独立 PDF 盲审未通过或已失效: " + status["reason"])


def completion_status(run_dir: Path) -> dict[str, Any]:
    """组合盲审与机械 QA，形成唯一的 complete 放行结论。"""
    review = paper_blind_review_status(run_dir)
    if not review["allowed"]:
        return {"allowed": False, "reason": review["reason"]}
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
        checks = mechanical.get("checks")
        if not isinstance(checks, list) or any(
            not isinstance(check, dict) or check.get("passed") is not True for check in checks
        ):
            return {"allowed": False, "reason": "机械 QA 缺少全部通过的检查记录"}
        if (
            mechanical.get("final_pdf") != "paper/final.pdf"
            or not pdf.is_file()
            or mechanical.get("final_pdf_sha256") != sha256_file(pdf)
        ):
            return {"allowed": False, "reason": "机械 QA 未绑定当前最终 PDF"}
        return {"allowed": True, "reason": ""}
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": "机械 QA 无法读取: " + str(exc)}


def require_completion_allowed(run_dir: Path) -> None:
    """要求独立审查与机械 QA 同时通过，禁止仅凭 PDF 完成状态交付。"""
    status = completion_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能标记 complete：" + status["reason"])
