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
from shumozizi.questions.acceptance import verify_question_acceptance
from shumozizi.questions.manifest import verify_problem_manifest
from shumozizi.results.sealing import verify_sealed_result
from shumozizi.workflow.approval import verify_route_approval
from shumozizi.workflow.integrity import verify_run_integrity
from shumozizi.workflow.reviews import (
    verify_review_adjudication,
    verify_review_receipt,
)
from shumozizi.workflow.source_package import SOURCE_MANIFEST_PATH, verify_source_manifest


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
    MODEL_SPEC_REVISED = "MODEL_SPEC_REVISED"


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


@dataclass(frozen=True)
class MachineBlocker:
    """不可由 AI 裁决覆盖的确定性审核门失败。"""

    blocker_id: str
    source: str
    override_allowed: bool
    evidence: list[str]


def collect_machine_blockers(
    run_dir: Path, gate_id: str, state: dict[str, Any]
) -> list[MachineBlocker]:
    """收集当前审核门可确定复验的硬失败事实。"""
    del state
    blockers: list[MachineBlocker] = []
    question_id = (
        gate_id.removeprefix("R2_EXPERIMENT_")
        if gate_id.startswith("R2_EXPERIMENT_")
        else None
    )
    if question_id is not None or gate_id == "R5_STANDARD_FINAL":
        registry_path = run_dir / "results" / "result_registry.json"
        if registry_path.is_file():
            try:
                registry = load_json(registry_path)
                require_valid(registry, "result_registry")
                for item in registry["results"]:
                    if item["status"] != "accepted":
                        continue
                    if question_id is not None and item["question_id"] != question_id:
                        continue
                    result_path = item.get("sealed_result_path")
                    seal_path = item.get("result_seal_path")
                    if result_path is None and seal_path is None:
                        continue
                    try:
                        verification = verify_sealed_result(run_dir, item["result_id"])
                        errors = verification["errors"]
                    except (ContractError, OSError, KeyError) as exc:
                        errors = [str(exc)]
                    if errors:
                        blockers.append(
                            MachineBlocker(
                                blocker_id=f"sealed-result-invalid:{item['result_id']}",
                                source="machine",
                                override_allowed=False,
                                evidence=errors,
                            )
                        )
            except (ContractError, OSError, KeyError) as exc:
                blockers.append(
                    MachineBlocker(
                        blocker_id="result-registry-invalid",
                        source="machine",
                        override_allowed=False,
                        evidence=[str(exc)],
                    )
                )
    if gate_id in {"R4_FORMAT_VISUAL", "R5_STANDARD_FINAL"}:
        final_pdf = run_dir / "paper" / "final.pdf"
        if not final_pdf.is_file():
            blockers.append(
                MachineBlocker(
                    blocker_id="final-pdf-missing",
                    source="machine",
                    override_allowed=False,
                    evidence=["paper/final.pdf 不存在"],
                )
            )
        audit_path = run_dir / "review" / "FORMAT_AUDIT.json"
        try:
            audit = load_json(audit_path)
            require_valid(audit, "format_audit")
            if audit["hard_failures"]:
                blockers.append(
                    MachineBlocker(
                        blocker_id="format-audit-hard-failure",
                        source="machine",
                        override_allowed=False,
                        evidence=list(audit["hard_failures"]),
                    )
                )
        except (ContractError, OSError, KeyError) as exc:
            blockers.append(
                MachineBlocker(
                    blocker_id="format-audit-invalid",
                    source="machine",
                    override_allowed=False,
                    evidence=[str(exc)],
                )
            )
    return blockers


def _latest_adjudication_path(receipt_path: Path) -> Path:
    """返回普通裁决或 probe 生命周期中编号最大的不可变裁决。"""
    fixed = receipt_path.with_name("REVIEW_ADJUDICATION.json")
    numbered = sorted(receipt_path.parent.glob("REVIEW_ADJUDICATION.[0-9][0-9][0-9][0-9].json"))
    if numbered:
        return numbered[-1]
    return fixed


TRANSITIONS: dict[tuple[str, WorkflowEvent], str] = {
    ("NEW", WorkflowEvent.ROUTES_PROPOSED): "WAITING_HUMAN_ROUTE",
    ("WAITING_HUMAN_ROUTE", WorkflowEvent.ROUTE_APPROVED): "ROUTE_LOCKED",
    ("ROUTE_LOCKED", WorkflowEvent.MODEL_SPEC_COMPLETED): "MODEL_SPEC_READY",
    ("MODEL_SPEC_READY", WorkflowEvent.MODEL_SPEC_REVISED): "MODEL_SPEC_READY",
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
    ("ROUTE_LOCKED", WorkflowEvent.ROUTE_DRIFT): "WAITING_HUMAN_ROUTE",
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
        if normalized_event is WorkflowEvent.MODEL_SPEC_REVISED:
            gate = state.setdefault("review_gates", {}).get("R1_MODELING")
            if gate and gate.get("receipt"):
                gate["status"] = "stale"
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
        if receipt["schema_version"] != "3.0":
            raise ContractError("v2 review receipt 仅允许历史只读验证，不能登记新审核门")
        adjudication_path = _latest_adjudication_path(resolved_receipt)
        request = load_json(resolved_receipt.with_name("review_request.json"))
        report = load_json(resolved_receipt.with_name("review_report.json"))
        previous_gate = state.get("review_gates", {}).get(gate_id, {})
        probe_rerecord = (
            previous_gate.get("status") == "failed"
            and previous_gate.get("reviewed_revision") == receipt["state_revision"]
            and previous_gate.get("recorded_revision") == state["revision"]
        )
        if receipt["state_revision"] != state["revision"] and not probe_rerecord:
            raise ContractError("审核回执不是针对当前 state revision 创建")
        adjudication_verification = verify_review_adjudication(
            run_dir,
            resolved_receipt.with_name("review_report.json"),
            adjudication_path,
            require_current_revision=False,
        )
        if not adjudication_verification["valid"]:
            raise ContractError(
                "审核裁决复验失败: "
                + "; ".join(adjudication_verification["errors"])
            )
        adjudication = load_json(adjudication_path)
        expected_stage, question_id = self._review_gate_identity(gate_id)
        if request["stage"] != expected_stage or report["stage"] != expected_stage:
            raise ContractError(f"审核回执阶段与门不一致: {gate_id}")
        if gate_id in {"R4_FORMAT_VISUAL", "R5_STANDARD_FINAL"}:
            source_report = verify_source_manifest(run_dir)
            if not source_report["valid"]:
                raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
            if request.get("binding_paths", {}).get("source_manifest") != SOURCE_MANIFEST_PATH:
                raise ContractError(f"{gate_id} 审核请求未绑定权威 SOURCE_MANIFEST.json")
        if question_id is not None and request.get("question_id") != question_id:
            raise ContractError(f"局部审核回执 question_id 不匹配: {question_id}")
        self._check_review_gate_timing(run_dir, state, gate_id, question_id)
        machine_blockers = collect_machine_blockers(run_dir, gate_id, state)
        accepted_blocking = [
            decision
            for decision in adjudication["decisions"]
            if decision["main_decision"] == "accepted"
            and decision["gate_effect"] == "block"
        ]
        unresolved = adjudication["unresolved_conflicts"]
        passed = not machine_blockers and not unresolved and not accepted_blocking
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
            "adjudication": adjudication_path.relative_to(run_dir).as_posix(),
            "adjudication_sha256": sha256_file(adjudication_path),
            "reviewed_revision": receipt["state_revision"],
            "recorded_revision": next_revision,
            "machine_blocker_count": len(machine_blockers),
            "accepted_blocking_finding_count": len(accepted_blocking),
            "question_id": question_id,
            "request_stage": expected_stage,
            "reviewer_verdict": report.get("verdict", ""),
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
                    ),
                    asdict(
                        ArtifactRef(
                            role=f"{gate_id}_ADJUDICATION",
                            path=adjudication_path.relative_to(run_dir).as_posix(),
                            sha256=sha256_file(adjudication_path),
                        )
                    ),
                ],
                "note": f"{gate_id}: {'passed' if passed else 'failed'}",
            }
        )
        require_valid(state, "workflow_state")
        atomic_json(state_path, state)
        return state

    def record_change_impact(
        self,
        run_id: str,
        change_level: str,
        affected_questions: list[str],
        actor: Actor,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """按 L0-L5 只失效受影响轨道和审核门，并记录定向返工状态。"""
        if change_level not in {"L0", "L1", "L2", "L3", "L4", "L5"}:
            raise ContractError(f"未知修改等级: {change_level}")
        run_dir = self.repo_root / "runs" / run_id
        state_path = run_dir / "state.json"
        state = load_json(state_path)
        require_valid(state, "workflow_state")
        if expected_revision is not None and state["revision"] != expected_revision:
            raise ContractError("状态 revision 已变化，拒绝登记修改影响")
        questions = sorted({item for item in affected_questions if item.strip()})
        known_questions = set(state.get("question_progress", {}))
        unknown = sorted(set(questions) - known_questions)
        if unknown and change_level in {"L2", "L3", "L4"}:
            raise ContractError("修改影响包含未知问题: " + ", ".join(unknown))

        gates = state.setdefault("review_gates", {})

        def stale_gate(gate_id: str) -> None:
            gate = gates.get(gate_id)
            if gate and gate.get("receipt") and gate.get("status") != "stale":
                gate["status"] = "stale"

        if change_level == "L1":
            stale_gate("R4_FORMAT_VISUAL")
        elif change_level == "L2":
            stale_gate("R3_PAPER_LOGIC")
            for question in questions:
                stale_gate(f"R3_PAPER_LOGIC_{question}")
        elif change_level in {"L3", "L4"}:
            if change_level == "L4":
                stale_gate("R1_MODELING")
            for question in questions:
                stale_gate(f"R2_EXPERIMENT_{question}")
                stale_gate(f"R3_PAPER_LOGIC_{question}")
            for gate_id in ("R3_PAPER_LOGIC", "R4_FORMAT_VISUAL", "R5_STANDARD_FINAL"):
                stale_gate(gate_id)
        elif change_level == "L5":
            for gate_id in tuple(gates):
                stale_gate(gate_id)

        tracks_by_level = {
            "L0": (),
            "L1": (),
            "L2": ("paper", "review"),
            "L3": ("experiment", "paper", "review"),
            "L4": ("model", "experiment", "paper", "review"),
            "L5": ("model", "experiment", "paper", "review"),
        }
        target_questions = questions or (
            sorted(known_questions) if change_level == "L5" else []
        )
        for question in target_questions:
            tracks = state["question_progress"].setdefault(question, {})
            for track in tracks_by_level[change_level]:
                if track in tracks and tracks[track] != "pending":
                    tracks[track] = "stale"

        fallback_status = {
            "L1": "PAPER_DRAFTED",
            "L2": "PAPER_DRAFTED",
            "L3": "EXPERIMENTING",
            "L4": "MODEL_SPEC_READY",
            "L5": "WAITING_HUMAN_ROUTE",
        }.get(change_level)
        status_order = [
            "NEW",
            "WAITING_HUMAN_ROUTE",
            "ROUTE_LOCKED",
            "MODEL_SPEC_READY",
            "EXPERIMENTING",
            "RESULTS_ACCEPTED",
            "PAPER_DRAFTED",
            "QA_RUNNING",
            "WAITING_HUMAN_FINAL",
            "COMPLETE",
        ]
        current = state["status"]
        if fallback_status == "WAITING_HUMAN_ROUTE" or (
            fallback_status
            and current in status_order
            and status_order.index(current) > status_order.index(fallback_status)
        ):
            state["status"] = fallback_status
            state["active_stage"] = ACTIVE_STAGES[fallback_status]
            state["route_locked"] = fallback_status != "WAITING_HUMAN_ROUTE"
            state["paper_ready"] = fallback_status in {
                "PAPER_DRAFTED",
                "QA_RUNNING",
                "WAITING_HUMAN_FINAL",
                "COMPLETE",
            }

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        state["revision"] += 1
        state["last_updated_by"] = actor.actor_id
        state["updated_at"] = now
        state["history"].append(
            {
                "from_status": current,
                "status": state["status"],
                "event": "CHANGE_IMPACT_RECORDED",
                "timestamp": now,
                "actor": asdict(actor),
                "artifact_refs": [],
                "note": f"{change_level}; affected_questions={','.join(questions) or 'none'}",
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
        if gate_id.startswith("R3_PAPER_LOGIC_"):
            question_id = gate_id.removeprefix("R3_PAPER_LOGIC_")
            if not question_id:
                raise ContractError("局部 R3 审核门缺少 question_id")
            return "R3_PAPER_LOGIC", question_id
        stage = REVIEW_GATE_STAGES.get(gate_id)
        if stage is None:
            raise ContractError(f"未知审核门: {gate_id}")
        return stage, None

    def _check_review_gate_timing(
        self,
        run_dir: Path,
        state: dict[str, Any],
        gate_id: str,
        question_id: str | None,
    ) -> None:
        """按材料依赖而非审核编号顺序限制登记时机。"""
        if gate_id == "R1_MODELING":
            allowed_statuses = {"ROUTE_LOCKED", "MODEL_SPEC_READY"}
        elif gate_id.startswith("R2_EXPERIMENT_"):
            allowed_statuses = {"EXPERIMENTING", "RESULTS_ACCEPTED", "PAPER_DRAFTED", "QA_RUNNING"}
        elif gate_id.startswith("R3_PAPER_LOGIC_"):
            allowed_statuses = {"EXPERIMENTING", "RESULTS_ACCEPTED", "PAPER_DRAFTED", "QA_RUNNING"}
        elif gate_id == "R3_PAPER_LOGIC":
            allowed_statuses = {"PAPER_DRAFTED", "QA_RUNNING"}
        elif gate_id == "R4_FORMAT_VISUAL":
            allowed_statuses = {"PAPER_DRAFTED", "QA_RUNNING"}
        else:
            allowed_statuses = {"QA_RUNNING"}
        if state["status"] not in allowed_statuses:
            raise ContractError(
                f"{gate_id} 当前状态不可登记；允许状态: {', '.join(sorted(allowed_statuses))}"
            )
        if question_id is not None:
            track = state.get("question_progress", {}).get(question_id, {})
            if gate_id.startswith("R2_EXPERIMENT_"):
                self._require_passed_review_gates(run_dir, state, ("R1_MODELING",))
                if track.get("experiment") not in {"ready", "accepted"}:
                    raise ContractError(f"{question_id} 实验未完成，不能登记 R2")
            elif gate_id.startswith("R3_PAPER_LOGIC_"):
                self._require_passed_review_gates(
                    run_dir, state, (f"R2_EXPERIMENT_{question_id}",)
                )
                if track.get("paper") not in {"ready", "accepted"}:
                    raise ContractError(f"{question_id} 章节未完成，不能登记局部 R3")
        if gate_id == "R5_STANDARD_FINAL":
            qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
            if qa.get("status") != "pass" or qa.get("hard_failures"):
                raise ContractError("R5 必须在 QA 机械检查通过后执行")
            self._require_current_production_integrity(run_dir)
        if gate_id == "J0_FINAL_BLIND_JUDGE":
            self._require_current_production_integrity(run_dir)
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
            manifest = verify_problem_manifest(run_dir)
            if not manifest["valid"]:
                raise ContractError("问题全集校验失败: " + "; ".join(manifest["errors"]))
            approval = verify_route_approval(run_dir)
            if not approval["valid"]:
                raise ContractError("路线批准复验失败: " + "; ".join(approval["errors"]))
        if event is WorkflowEvent.ROUTE_DRIFT and not {"drift_memo", "approval_request"}.issubset(
            roles
        ):
            raise ContractError("路线漂移必须附带 drift memo 与新批准请求")
        if event is WorkflowEvent.MODEL_SPEC_REVISED:
            self._verify_model_spec_revision(run_dir, refs)
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
            self._require_current_production_integrity(
                run_dir,
                expected_state_revision=state["revision"],
            )
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
            final_gate_ids = (
                "R3_PAPER_LOGIC",
                "R4_FORMAT_VISUAL",
                "R5_STANDARD_FINAL",
            )
            self._require_gate_presence(state, final_gate_ids)
            source_report = verify_source_manifest(run_dir)
            if not source_report["valid"]:
                raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
            if qa.get("source_manifest_sha256") != source_report["manifest_sha256"]:
                raise ContractError("QA 报告未绑定当前 SOURCE_MANIFEST.json")
            self._require_current_production_integrity(run_dir)
            integrity = verify_run_integrity(
                run_dir, "WAITING_HUMAN_FINAL", repo_root=self.repo_root
            )
            if not integrity["valid"]:
                raise ContractError("运行完整性校验失败: " + "; ".join(integrity["errors"]))
            self._require_passed_review_gates(
                run_dir,
                state,
                (
                    *final_gate_ids,
                ),
            )
        if event is WorkflowEvent.FINAL_APPROVED:
            self._assert_complete_invariants(run_dir, state)
            integrity = verify_run_integrity(run_dir, "COMPLETE", repo_root=self.repo_root)
            if not integrity["valid"]:
                raise ContractError(
                    "COMPLETE 运行完整性校验失败: " + "; ".join(integrity["errors"])
                )

    @staticmethod
    def _verify_model_spec_revision(run_dir: Path, refs: list[ArtifactRef]) -> None:
        """验证规格修订没有越过当前路线锁边界。"""
        by_role: dict[str, ArtifactRef] = {}
        for ref in refs:
            if ref.role in by_role:
                raise ContractError(f"规格修订事件存在重复产物角色: {ref.role}")
            by_role[ref.role] = ref
        required = {"old_model_spec", "new_model_spec", "repair_plan", "route_lock"}
        if not required.issubset(by_role):
            missing = ", ".join(sorted(required - set(by_role)))
            raise ContractError(f"规格修订事件缺少产物: {missing}")

        canonical_spec = (run_dir / "brief" / "model_spec.json").resolve()
        canonical_lock = (run_dir / "brief" / "ROUTE_LOCK.json").resolve()
        new_spec_path = (run_dir / by_role["new_model_spec"].path).resolve()
        route_lock_path = (run_dir / by_role["route_lock"].path).resolve()
        if new_spec_path != canonical_spec or route_lock_path != canonical_lock:
            raise ContractError("规格修订必须绑定权威 model_spec.json 与 ROUTE_LOCK.json")

        old_spec_path = (run_dir / by_role["old_model_spec"].path).resolve()
        repair_path = (run_dir / by_role["repair_plan"].path).resolve()
        old_spec = load_json(old_spec_path)
        new_spec = load_json(new_spec_path)
        repair = load_json(repair_path)
        require_valid(old_spec, "model_spec")
        require_valid(new_spec, "model_spec")
        require_valid(repair, "repair_plan")
        route_lock_sha256 = sha256_file(route_lock_path)
        if old_spec["route_lock_sha256"] != route_lock_sha256:
            raise ContractError("旧模型规格未绑定当前路线锁")
        if new_spec["route_lock_sha256"] != route_lock_sha256:
            raise ContractError("新模型规格改变或未绑定当前路线锁")
        if sha256_file(old_spec_path) == sha256_file(new_spec_path):
            raise ContractError("MODEL_SPEC_REVISED 要求模型规格实际发生变化")
        if repair["route_reapproval_required"]:
            raise ContractError("修复计划要求路线重批时不能使用 MODEL_SPEC_REVISED")

    @staticmethod
    def _require_gate_presence(state: dict[str, Any], gate_ids: tuple[str, ...]) -> None:
        """先以稳定错误优先级报告缺失审核门，再执行哈希复验。"""
        gates = state.get("review_gates", {})
        for gate_id in gate_ids:
            gate = gates.get(gate_id, {})
            if gate.get("status") != "passed" or not gate.get("receipt"):
                raise ContractError(f"审核门未通过或缺少回执: {gate_id}")

    @staticmethod
    def _require_current_production_integrity(
        run_dir: Path,
        *,
        expected_state_revision: int | None = None,
    ) -> None:
        """复验当前论文、图表和逐问验收生产事实。"""
        production = verify_production_receipts(
            run_dir,
            expected_state_revision=expected_state_revision,
        )
        if not production["valid"]:
            raise ContractError(
                "论文或图表生产回执校验失败: " + "; ".join(production["errors"])
            )
        acceptance = verify_question_acceptance(run_dir)
        if not acceptance["valid"]:
            raise ContractError("逐问验收校验失败: " + "; ".join(acceptance["errors"]))

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
        manifest = load_json(run_dir / "problem/PROBLEM_MANIFEST.json")
        required_reviews = tuple(
            ["R1_MODELING"]
            + [
                f"R2_EXPERIMENT_{item['question_id']}"
                for item in manifest["questions"]
                if item["required"]
            ]
            + [
                "R3_PAPER_LOGIC",
                "R4_FORMAT_VISUAL",
                "R5_STANDARD_FINAL",
            ]
        )
        self._require_passed_review_gates(run_dir, state, required_reviews)
        approval = verify_route_approval(run_dir)
        if not approval["valid"]:
            raise ContractError("COMPLETE 路线批准复验失败: " + "; ".join(approval["errors"]))
        self._require_current_production_integrity(run_dir)
        source_report = verify_source_manifest(run_dir)
        if not source_report["valid"]:
            raise ContractError("COMPLETE 源码包校验失败: " + "; ".join(source_report["errors"]))
        verify_run_config_lock(self.repo_root, run_dir)
        qa_path = run_dir / "review" / "QA_AGGREGATE.json"
        format_audit_path = run_dir / "review" / "FORMAT_AUDIT.json"
        evidence_path = run_dir / "review" / "EVIDENCE_VALIDATION.json"
        request_path = run_dir / "review" / "final_approval_request.json"
        receipt_path = run_dir / "review" / "final_approval_receipt.json"
        qa, format_audit, evidence, request, receipt = map(
            load_json,
            (qa_path, format_audit_path, evidence_path, request_path, receipt_path),
        )
        require_valid(receipt, "final_approval_receipt")
        if qa.get("status") != "pass" or qa.get("hard_failures"):
            raise ContractError("COMPLETE 要求 QA 聚合无 hard failure")
        if evidence.get("status") != "pass":
            raise ContractError("COMPLETE 要求证据校验通过")
        if format_audit.get("hard_failures"):
            raise ContractError("COMPLETE 要求 FORMAT_AUDIT 无机器硬失败")
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
            "format_audit_sha256": sha256_file(format_audit_path),
            "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json"),
            "source_manifest_sha256": source_report["manifest_sha256"],
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
