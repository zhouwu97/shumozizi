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
from shumozizi.paper.receipts import verify_production_receipts
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.results.sealing import verify_sealed_result
from shumozizi.workflow.reviews import verify_review_receipt


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
REVIEW_GATE_STAGES = {
    "R1_MODELING": "R1_MODELING",
    "R3_PAPER_LOGIC": "R3_PAPER_LOGIC",
    "R4_FORMAT_VISUAL": "R4_FORMAT_VISUAL",
    "R5_STANDARD_FINAL": "R5_COMPREHENSIVE",
    "J0_FINAL_BLIND_JUDGE": "J0_FINAL_BLIND_JUDGE",
}


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

    def record_review_gate(
        self,
        run_id: str,
        gate_id: str,
        receipt_path: Path,
        actor: Actor,
    ) -> dict[str, Any]:
        """复验审核回执并把阶段证明写入同一工作流状态。"""
        run_dir = self.repo_root / "runs" / run_id
        state_path = run_dir / "state.json"
        state = load_json(state_path)
        require_valid(state, "workflow_state")
        resolved_receipt = receipt_path.resolve()
        try:
            relative_receipt = resolved_receipt.relative_to(run_dir.resolve()).as_posix()
        except ValueError as exc:
            raise ContractError("审核回执路径越过运行目录边界") from exc
        verification = verify_review_receipt(
            run_dir, resolved_receipt, require_current_revision=False
        )
        if not verification["valid"]:
            raise ContractError("审核回执复验失败: " + "; ".join(verification["errors"]))
        receipt = load_json(resolved_receipt)
        request = load_json(resolved_receipt.with_name("review_request.json"))
        report = load_json(resolved_receipt.with_name("review_report.json"))
        if receipt["state_revision"] != state["revision"]:
            raise ContractError("审核回执不是针对当前 state revision 创建")
        expected_stage, question_id = self._review_gate_identity(gate_id)
        if request["stage"] != expected_stage or report["stage"] != expected_stage:
            raise ContractError(f"审核回执阶段与门不一致: {gate_id}")
        if question_id is not None and request.get("question_id") != question_id:
            raise ContractError(f"R2 审核回执 question_id 不匹配: {question_id}")
        self._check_review_gate_timing(run_dir, state, gate_id, question_id)
        passed = self._review_gate_passed(gate_id, receipt, report)
        if gate_id == "J0_FINAL_BLIND_JUDGE" and state.get("review_gates", {}).get(
            gate_id, {}
        ).get("receipt"):
            raise ContractError("J0_FINAL_BLIND_JUDGE 只允许登记一次")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        next_revision = state["revision"] + 1
        state.setdefault("review_gates", {})[gate_id] = {
            "status": "passed" if passed else "failed",
            "receipt": relative_receipt,
            "receipt_sha256": sha256_file(resolved_receipt),
            "reviewed_revision": receipt["state_revision"],
            "recorded_revision": next_revision,
            "question_id": question_id,
            "request_stage": expected_stage,
        }
        state["revision"] = next_revision
        state["last_updated_by"] = actor.actor_id
        state["updated_at"] = now
        state["history"].append(
            {
                "from_status": state["status"],
                "status": state["status"],
                "event": "REVIEW_GATE_RECORDED",
                "timestamp": now,
                "actor": asdict(actor),
                "artifact_refs": [
                    asdict(
                        ArtifactRef(
                            role=gate_id,
                            path=relative_receipt,
                            sha256=sha256_file(resolved_receipt),
                        )
                    )
                ],
                "note": f"{gate_id}: {'passed' if passed else 'failed'}",
            }
        )
        require_valid(state, "workflow_state")
        atomic_json(state_path, state)
        return state

    @staticmethod
    def _review_gate_identity(gate_id: str) -> tuple[str, str | None]:
        """解析审核门对应的请求阶段和可选题号。"""
        if gate_id.startswith("R2_EXPERIMENT_"):
            question_id = gate_id.removeprefix("R2_EXPERIMENT_")
            if not question_id:
                raise ContractError("R2 审核门缺少 question_id")
            return "R2_EXPERIMENT", question_id
        stage = REVIEW_GATE_STAGES.get(gate_id)
        if stage is None:
            raise ContractError(f"未知审核门: {gate_id}")
        return stage, None

    @staticmethod
    def _review_gate_passed(
        gate_id: str, receipt: dict[str, Any], report: dict[str, Any]
    ) -> bool:
        """按各审核阶段的结论规则判断是否通过。"""
        if receipt.get("decision") not in {"accepted", "accepted_with_warnings"}:
            return False
        verdicts = {
            "R1_MODELING": {"ACCEPT", "ACCEPT_WITH_FIXES"},
            "R2_EXPERIMENT": {"REPRODUCIBLE", "REPRODUCIBLE_WITH_WARNINGS"},
            "R3_PAPER_LOGIC": {"READY_FOR_COMPREHENSIVE_REVIEW"},
            "R4_FORMAT_VISUAL": {"COMPLIANT"},
            "J0_FINAL_BLIND_JUDGE": {"PROCEED", "DO_NOT_PROCEED", "ADVISORY"},
        }
        request_stage = report["stage"]
        if gate_id == "R5_STANDARD_FINAL":
            grade = report.get("rating", {}).get("grade")
            severe = any(
                finding.get("severity") in {"P0", "P1"}
                for finding in report.get("findings", [])
            )
            return grade in {"A", "B"} and not severe
        return report.get("verdict") in verdicts[request_stage]

    def _check_review_gate_timing(
        self,
        run_dir: Path,
        state: dict[str, Any],
        gate_id: str,
        question_id: str | None,
    ) -> None:
        """保证每类审核只在主状态链规定的阶段登记。"""
        expected_status = {
            "R1_MODELING": "MODEL_SPEC_READY",
            "R3_PAPER_LOGIC": "PAPER_DRAFTED",
            "R4_FORMAT_VISUAL": "PAPER_DRAFTED",
            "R5_STANDARD_FINAL": "QA_RUNNING",
            "J0_FINAL_BLIND_JUDGE": "QA_RUNNING",
        }.get(gate_id, "EXPERIMENTING")
        if state["status"] != expected_status:
            raise ContractError(f"{gate_id} 只能在 {expected_status} 阶段登记")
        if question_id is not None:
            track = state.get("question_progress", {}).get(question_id, {})
            if track.get("experiment") not in {"ready", "accepted"}:
                raise ContractError(f"{question_id} 实验未完成，不能登记 R2")
        if gate_id == "R5_STANDARD_FINAL":
            qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
            if qa.get("status") != "pass" or qa.get("hard_failures"):
                raise ContractError("R5 必须在 QA 机械检查通过后执行")
        if gate_id == "J0_FINAL_BLIND_JUDGE":
            self._require_passed_review_gates(
                run_dir, state, ("R5_STANDARD_FINAL",)
            )

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
        if event is WorkflowEvent.EXPERIMENT_STARTED:
            self._require_passed_review_gates(run_dir, state, ("R1_MODELING",))
        if event is WorkflowEvent.RESULTS_ADMITTED:
            completed_questions = [
                question_id
                for question_id, tracks in state.get("question_progress", {}).items()
                if tracks.get("experiment") in {"ready", "accepted"}
            ]
            if not completed_questions:
                raise ContractError("RESULTS_ADMITTED 要求至少一个问级实验已完成")
            self._require_passed_review_gates(
                run_dir,
                state,
                tuple(f"R2_EXPERIMENT_{question_id}" for question_id in completed_questions),
            )
        if event is WorkflowEvent.PAPER_COMPLETED:
            production = verify_production_receipts(run_dir)
            if not production["valid"]:
                raise ContractError("论文或图表生产回执校验失败: " + "; ".join(production["errors"]))
        if event is WorkflowEvent.QA_STARTED:
            self._require_passed_review_gates(
                run_dir, state, ("R3_PAPER_LOGIC", "R4_FORMAT_VISUAL")
            )
        if event is WorkflowEvent.QA_BLOCKED:
            qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
            if qa.get("status") != "blocked":
                raise ContractError("只有 QA hard failure 可以触发 BLOCKED")
        if event is WorkflowEvent.QA_PASSED:
            qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
            if qa.get("status") != "pass" or qa.get("hard_failures"):
                raise ContractError("QA 未通过，不能等待最终批准")
            self._require_passed_review_gates(
                run_dir,
                state,
                (
                    "R3_PAPER_LOGIC",
                    "R4_FORMAT_VISUAL",
                    "R5_STANDARD_FINAL",
                    "J0_FINAL_BLIND_JUDGE",
                ),
            )
        if event is WorkflowEvent.FINAL_APPROVED:
            self._assert_complete_invariants(run_dir, state)

    @staticmethod
    def _require_passed_review_gates(
        run_dir: Path, state: dict[str, Any], gate_ids: tuple[str, ...]
    ) -> None:
        """要求指定审核门均通过，且回执仍绑定当前生产事实。"""
        gates = state.get("review_gates", {})
        for gate_id in gate_ids:
            gate = gates.get(gate_id, {})
            if gate.get("status") != "passed" or not gate.get("receipt"):
                raise ContractError(f"审核门未通过或缺少回执: {gate_id}")
            receipt_path = run_dir / gate["receipt"]
            if not receipt_path.is_file() or gate.get("receipt_sha256") != sha256_file(
                receipt_path
            ):
                raise ContractError(f"审核回执不存在或哈希失效: {gate_id}")
            verification = verify_review_receipt(
                run_dir, receipt_path, require_current_revision=False
            )
            if not verification["valid"]:
                raise ContractError(
                    f"审核回执绑定已失效: {gate_id}: "
                    + "; ".join(verification["errors"])
                )

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
