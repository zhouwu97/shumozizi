"""提供写入 ``state.json`` 的唯一状态推进服务。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.results.sealing import verify_sealed_result


class WorkflowEvent(StrEnum):
    """能够推进工作流的受控事件。"""

    ROUTES_PROPOSED = "ROUTES_PROPOSED"
    ROUTE_APPROVED = "ROUTE_APPROVED"
    MODEL_SPEC_COMPLETED = "MODEL_SPEC_COMPLETED"
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    RESULTS_ADMITTED = "RESULTS_ADMITTED"
    PAPER_COMPLETED = "PAPER_COMPLETED"
    QA_STARTED = "QA_STARTED"
    QA_BLOCKED = "QA_BLOCKED"
    FIX_APPLIED = "FIX_APPLIED"
    QA_PASSED = "QA_PASSED"
    FINAL_APPROVED = "FINAL_APPROVED"
    ROUTE_DRIFT = "ROUTE_DRIFT"


@dataclass(frozen=True)
class Actor:
    """记录状态事件责任主体。"""

    actor_id: str
    actor_type: str = "codex"


@dataclass(frozen=True)
class ArtifactRef:
    """记录触发状态变化的运行内产物。"""

    role: str
    path: str
    sha256: str | None = None


TRANSITIONS: dict[tuple[str, WorkflowEvent], str] = {
    ("NEW", WorkflowEvent.ROUTES_PROPOSED): "WAITING_HUMAN_ROUTE",
    ("WAITING_HUMAN_ROUTE", WorkflowEvent.ROUTE_APPROVED): "ROUTE_LOCKED",
    ("ROUTE_LOCKED", WorkflowEvent.MODEL_SPEC_COMPLETED): "MODEL_SPEC_READY",
    ("MODEL_SPEC_READY", WorkflowEvent.EXPERIMENT_STARTED): "EXPERIMENTING",
    ("EXPERIMENTING", WorkflowEvent.RESULTS_ADMITTED): "RESULTS_ACCEPTED",
    ("RESULTS_ACCEPTED", WorkflowEvent.PAPER_COMPLETED): "PAPER_DRAFTED",
    ("PAPER_DRAFTED", WorkflowEvent.QA_STARTED): "QA_RUNNING",
    ("QA_RUNNING", WorkflowEvent.QA_BLOCKED): "BLOCKED",
    ("BLOCKED", WorkflowEvent.FIX_APPLIED): "PAPER_DRAFTED",
    ("QA_RUNNING", WorkflowEvent.QA_PASSED): "WAITING_HUMAN_FINAL",
    ("WAITING_HUMAN_FINAL", WorkflowEvent.FIX_APPLIED): "PAPER_DRAFTED",
    ("WAITING_HUMAN_FINAL", WorkflowEvent.FINAL_APPROVED): "COMPLETE",
    ("MODEL_SPEC_READY", WorkflowEvent.ROUTE_DRIFT): "WAITING_HUMAN_ROUTE",
    ("EXPERIMENTING", WorkflowEvent.ROUTE_DRIFT): "WAITING_HUMAN_ROUTE",
    ("BLOCKED", WorkflowEvent.ROUTE_DRIFT): "WAITING_HUMAN_ROUTE",
}


ACTIVE_STAGES = {
    "NEW": "ingest",
    "WAITING_HUMAN_ROUTE": "route_approval",
    "ROUTE_LOCKED": "model_spec",
    "MODEL_SPEC_READY": "experiment",
    "EXPERIMENTING": "experiment",
    "RESULTS_ACCEPTED": "paper",
    "PAPER_DRAFTED": "qa",
    "QA_RUNNING": "qa",
    "BLOCKED": "targeted_fix",
    "WAITING_HUMAN_FINAL": "final_approval",
    "COMPLETE": None,
}

QUESTION_TRACKS = {"model", "experiment", "paper", "review"}
TRACK_STATUSES = {"pending", "in_progress", "ready", "blocked", "accepted", "stale"}


class StateService:
    """对指定仓库中的运行执行受控状态推进。"""

    def __init__(self, repo_root: Path):
        """绑定仓库根。"""
        self.repo_root = repo_root.resolve()

    def transition(
        self,
        run_id: str,
        event: WorkflowEvent,
        actor: Actor,
        artifact_refs: list[ArtifactRef],
    ) -> dict[str, Any]:
        """验证事件及不变量后原子更新状态。"""
        run_dir = self.repo_root / "runs" / run_id
        state_path = run_dir / "state.json"
        state = load_json(state_path)
        require_valid(state, "workflow_state")
        try:
            normalized_event = WorkflowEvent(event)
        except ValueError as exc:
            raise ContractError(f"未知工作流事件: {event}") from exc
        current = state["status"]
        target = TRANSITIONS.get((current, normalized_event))
        if target is None:
            raise ContractError(f"非法状态转换: {current} --{normalized_event}--> ?")
        self._verify_artifact_refs(run_dir, artifact_refs)
        self._check_event_invariants(run_dir, state, normalized_event, artifact_refs)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        state["status"] = target
        state["revision"] += 1
        state["active_stage"] = ACTIVE_STAGES[target]
        state["route_locked"] = target not in {"NEW", "WAITING_HUMAN_ROUTE"}
        state["paper_ready"] = target in {
            "PAPER_DRAFTED",
            "QA_RUNNING",
            "BLOCKED",
            "WAITING_HUMAN_FINAL",
            "COMPLETE",
        }
        if current not in state["completed_stages"]:
            state["completed_stages"].append(current)
        state["last_updated_by"] = actor.actor_id
        state["updated_at"] = now
        state["history"].append(
            {
                "from_status": current,
                "status": target,
                "event": normalized_event.value,
                "timestamp": now,
                "actor": asdict(actor),
                "artifact_refs": [asdict(item) for item in artifact_refs],
            }
        )
        require_valid(state, "workflow_state")
        atomic_json(state_path, state)
        return state

    def update_question_progress(
        self,
        run_id: str,
        question_id: str,
        track: str,
        status: str,
        actor: Actor,
        *,
        expected_revision: int | None = None,
        artifact_refs: list[ArtifactRef] | None = None,
    ) -> dict[str, Any]:
        """原子更新问级 model/experiment/paper/review 轨道并递增 revision。"""
        if not question_id.strip() or track not in QUESTION_TRACKS or status not in TRACK_STATUSES:
            raise ContractError("问级轨道参数不合法")
        run_dir = self.repo_root / "runs" / run_id
        state_path = run_dir / "state.json"
        state = load_json(state_path)
        require_valid(state, "workflow_state")
        if expected_revision is not None and state["revision"] != expected_revision:
            raise ContractError("状态 revision 已变化，拒绝覆盖其他任务进度")
        refs = artifact_refs or []
        self._verify_artifact_refs(run_dir, refs)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        previous = state["question_progress"].get(question_id, {}).get(track, "pending")
        state["question_progress"].setdefault(question_id, {})[track] = status
        state["revision"] += 1
        state["last_updated_by"] = actor.actor_id
        state["updated_at"] = now
        state["history"].append(
            {
                "from_status": state["status"],
                "status": state["status"],
                "event": "QUESTION_TRACK_UPDATED",
                "timestamp": now,
                "actor": asdict(actor),
                "artifact_refs": [asdict(item) for item in refs],
                "note": f"{question_id}.{track}: {previous} -> {status}",
            }
        )
        require_valid(state, "workflow_state")
        atomic_json(state_path, state)
        return state

    @staticmethod
    def _verify_artifact_refs(run_dir: Path, refs: list[ArtifactRef]) -> None:
        """复验所有事件产物都位于运行目录内且哈希匹配。"""
        for ref in refs:
            path = (run_dir / ref.path).resolve()
            if run_dir.resolve() not in path.parents or not path.is_file():
                raise ContractError(f"状态事件产物不存在或越界: {ref.path}")
            if ref.sha256 is not None and sha256_file(path) != ref.sha256:
                raise ContractError(f"状态事件产物哈希不一致: {ref.path}")

    def _check_event_invariants(
        self,
        run_dir: Path,
        state: dict[str, Any],
        event: WorkflowEvent,
        refs: list[ArtifactRef],
    ) -> None:
        """检查需要跨文件权威事实的事件。"""
        roles = {item.role for item in refs}
        if event is WorkflowEvent.ROUTE_APPROVED:
            if not {"route_approval_receipt", "route_lock"}.issubset(roles):
                raise ContractError("路线批准事件必须附带批准回执与路线锁")
        if event is WorkflowEvent.ROUTE_DRIFT and not {"drift_memo", "approval_request"}.issubset(
            roles
        ):
            raise ContractError("路线漂移必须附带 drift memo 与新批准请求")
        if event is WorkflowEvent.QA_BLOCKED:
            qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
            if qa.get("status") != "blocked":
                raise ContractError("只有 QA hard failure 可以触发 BLOCKED")
        if event is WorkflowEvent.QA_PASSED:
            qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
            if qa.get("status") != "pass" or qa.get("hard_failures"):
                raise ContractError("QA 未通过，不能等待最终批准")
        if event is WorkflowEvent.FINAL_APPROVED:
            self._assert_complete_invariants(run_dir, state)

    def _assert_complete_invariants(self, run_dir: Path, state: dict[str, Any]) -> None:
        """复验 COMPLETE 所绑定的全部当前事实。"""
        if state.get("paper_ready") is not True:
            raise ContractError("COMPLETE 要求 paper_ready=true")
        verify_run_config_lock(self.repo_root, run_dir)
        qa_path = run_dir / "review" / "QA_AGGREGATE.json"
        evidence_path = run_dir / "review" / "EVIDENCE_VALIDATION.json"
        request_path = run_dir / "review" / "final_approval_request.json"
        receipt_path = run_dir / "review" / "final_approval_receipt.json"
        qa, evidence, request, receipt = map(
            load_json, (qa_path, evidence_path, request_path, receipt_path)
        )
        require_valid(receipt, "final_approval_receipt")
        if qa.get("status") != "pass" or qa.get("hard_failures"):
            raise ContractError("COMPLETE 要求 QA 聚合无 hard failure")
        if evidence.get("status") != "pass":
            raise ContractError("COMPLETE 要求证据校验通过")
        registry = load_json(run_dir / "results" / "result_registry.json")
        for item in registry.get("results", []):
            if item.get("status") == "accepted":
                verification = verify_sealed_result(run_dir, item["result_id"])
                if not verification["valid"]:
                    raise ContractError(
                        "COMPLETE 要求全部 sealed result 可验证: "
                        + "; ".join(verification["errors"])
                    )
        current = {
            "final_pdf_sha256": sha256_file(run_dir / request["final_pdf_path"]),
            "qa_report_sha256": sha256_file(qa_path),
            "evidence_report_sha256": sha256_file(evidence_path),
            "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json"),
        }
        if receipt.get("approval_request_sha256") != sha256_file(request_path):
            raise ContractError("最终批准回执未绑定当前请求")
        for key, value in current.items():
            if request.get("bindings", {}).get(key) != value:
                raise ContractError(f"最终批准请求已失效: {key}")
            if receipt.get(key) != value:
                raise ContractError(f"最终批准回执已失效: {key}")


def transition(
    run_id: str,
    event: WorkflowEvent,
    actor: Actor,
    artifact_refs: list[ArtifactRef],
) -> dict[str, Any]:
    """使用当前仓库根执行状态转换。"""
    return StateService(resolve_repo_root()).transition(run_id, event, actor, artifact_refs)


def update_question_progress(
    run_id: str,
    question_id: str,
    track: str,
    status: str,
    actor: Actor,
    *,
    expected_revision: int | None = None,
    artifact_refs: list[ArtifactRef] | None = None,
) -> dict[str, Any]:
    """使用当前仓库根更新问级轨道。"""
    return StateService(resolve_repo_root()).update_question_progress(
        run_id,
        question_id,
        track,
        status,
        actor,
        expected_revision=expected_revision,
        artifact_refs=artifact_refs,
    )
