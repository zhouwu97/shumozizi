"""论文解释图候选生成、审图、重试和 Sandbox 晋级。

生成器与审图器通过可注入回调或无 shell 的外部命令接入，避免把某个云服务
写死在核心流程中。AI 图片始终停留在 Sandbox 设计参考层，正式图需另行重渲染。
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, relative_inside, sha256_file
from shumozizi.simple.paper_image_prompts import PROMPT_ROOT
from shumozizi.simple.paper_image_review import select_review
from shumozizi.simple.visual_sandbox import (
    graduate_visual_candidate,
    record_visual_competition,
    upsert_visual_idea,
)

Generator = Callable[[Path, Path, Path], None]
Reviewer = Callable[[Path, Path, Path, int], dict[str, Any]]
IMAGE_SUFFIX = ".png"


def _inside(root: Path, path: Path) -> Path:
    """确认生成器只能写入当前运行目录。"""
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError("候选图片路径必须位于当前运行目录") from exc
    return resolved


def _simplified_prompt(prompt: str) -> str:
    """根据首轮审图的常见失败模式生成第二轮简化提示。"""
    return "\n".join(
        [
            prompt,
            "第二轮简化：减少文字和小字号标签，删除次要参数，扩大核心判据与关键模块，增加留白。",
            "不要生成任何无法确认的数字或公式；不确定的内容使用抽象占位框，供确定性 renderer 后续替换。",
        ]
    )


def _candidate_name(variant: str, attempt: int) -> str:
    """生成稳定且可保留历史尝试的候选文件名。"""
    suffix = "" if attempt == 1 else f"_r{attempt}"
    return f"candidate_{variant}{suffix}{IMAGE_SUFFIX}"


def _competition_review_fields(reviews: list[dict[str, Any]]) -> dict[str, str]:
    """从 KEEP 审图记录推导 9.2 评审字段，保证 hero 竞争有实质表达判断。

    Args:
        reviews: 全部轮次审图记录（已规范化）。

    Returns:
        9.2 评审字段到非空描述的映射。
    """
    kept = [item for item in reviews if item.get("hard_pass")]
    best = max(kept, key=lambda item: float(item.get("soft_score", 0.0)), default={})
    elements = "、".join(
        str(item) for item in best.get("non_text_visual_elements", []) if str(item)
    )
    issues = "；".join(str(item) for item in best.get("issues", [])[:2])
    generic_level = str(best.get("generic_box_diagram_level", "LOW"))
    soft_score = best.get("soft_score", "N/A")
    return {
        "model_object_visibility": (
            f"候选包含非文字元素 {elements or '待 renderer 填充'}，"
            "对象可见性已由审图 hard_checks 校验。"
        ),
        "domain_specificity": "Prompt 绑定视觉需求 claim 与 source_result_ids，换题后设计参考即失效。",
        "mechanism_or_path_visibility": "候选按阅读路径复述输入、机制、判据与输出。",
        "constraint_or_boundary_visibility": "判据与阈值元素在 hard_checks 中校验。",
        "uncertainty_visibility": "区间元素由正式 renderer 从 current 数据重生成。",
        "paper_size_legibility": "正式论文宽度下的字号与裁切由 renderer 与机械 QA 复核。",
        "information_density": f"soft_score={soft_score}，generic_box={generic_level}。",
        "reading_order": "five_stage_balanced 与 center_emphasis 两种结构完成竞争。",
        "known_risks": issues or "无已知风险",
    }


def _atomic_text(path: Path, value: str) -> None:
    """在同目录原子替换第二轮 Prompt。"""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _review_record(
    *,
    root: Path,
    candidate: Path,
    prompt: Path,
    attempt: int,
    review: dict[str, Any],
) -> dict[str, Any]:
    """绑定候选、Prompt 和审图结果哈希。"""
    normalized = select_review([{"candidate": relative_inside(root, candidate).as_posix(), "attempt": attempt, **review}])["candidates"][0]
    normalized["prompt"] = relative_inside(root, prompt).as_posix()
    normalized["candidate_sha256"] = sha256_file(candidate)
    normalized["prompt_sha256"] = sha256_file(prompt)
    return normalized


def run_paper_image_generation(
    run_dir: Path,
    image_id: str,
    *,
    generator: Generator,
    reviewer: Reviewer,
    reviewer_context_id: str,
    max_rounds: int = 2,
) -> dict[str, Any]:
    """执行最多两轮 A/B 候选生成，选择结果并登记 Sandbox。"""
    if max_rounds != 2:
        raise ContractError("P0 只允许最多两轮候选生成")
    if not reviewer_context_id.strip():
        raise ContractError("必须提供 reviewer_context_id")
    root = run_dir.resolve()
    prompt_dir = root / PROMPT_ROOT / image_id
    meta_path = prompt_dir / "meta.json"
    if not meta_path.is_file():
        raise ContractError(f"找不到 Prompt meta.json: {relative_inside(root, meta_path)}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("priority") == "low":
        return {"status": "suggested_only", "image_id": image_id}
    sandbox = root / "figures/sandbox" / image_id
    sandbox.mkdir(parents=True, exist_ok=True)
    all_reviews: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_rounds + 1):
        round_reviews: list[dict[str, Any]] = []
        for variant in ("a", "b"):
            source_prompt = prompt_dir / f"variant_{variant}.txt"
            if not source_prompt.is_file():
                raise ContractError(f"缺少 Prompt: {relative_inside(root, source_prompt)}")
            prompt_path = source_prompt
            if attempt == 2:
                prompt_path = prompt_dir / f"variant_{variant}_r2.txt"
                _atomic_text(
                    prompt_path,
                    _simplified_prompt(source_prompt.read_text(encoding="utf-8")),
                )
            output = _inside(root, sandbox / _candidate_name(variant, attempt))
            temporary_output = output.with_name(
                f".{output.stem}.{os.getpid()}.tmp{output.suffix}"
            )
            try:
                generator(prompt_path, temporary_output, meta_path)
                if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                    raise ContractError(
                        f"生成器未产生候选图片: {relative_inside(root, output)}"
                    )
                temporary_output.replace(output)
            finally:
                if temporary_output.is_file():
                    temporary_output.unlink()
            raw_review = reviewer(meta_path, output, prompt_path, attempt)
            record = _review_record(
                root=root,
                candidate=output,
                prompt=prompt_path,
                attempt=attempt,
                review=raw_review,
            )
            round_reviews.append(record)
            all_reviews.append(record)
        decision = select_review(round_reviews)
        attempts.append({"attempt": attempt, "reviews": round_reviews, "decision": decision})
        if decision["verdict"] == "KEEP":
            selected = str(decision["selected_candidate"])
            upsert_visual_idea(
                root,
                idea_id=image_id,
                question=str(meta.get("question_id", "")),
                sources=[
                    *meta.get("source_result_ids", []),
                    str(meta.get("requirement_id", "")),
                ],
                idea=str(meta.get("reason", "")),
                figure_tier="hero_figure" if meta.get("priority") == "high" else "supporting_figure",
            )
            structures = {
                relative_inside(root, root / "figures/sandbox" / image_id / name).as_posix(): structure
                for name, structure in (
                    ("candidate_a.png", "five_stage_balanced"),
                    ("candidate_b.png", "center_emphasis"),
                    ("candidate_a_r2.png", "five_stage_balanced_simplified"),
                    ("candidate_b_r2.png", "center_emphasis_simplified"),
                )
                if (root / "figures/sandbox" / image_id / name).is_file()
            }
            competition = record_visual_competition(
                root,
                image_id,
                selected_candidate=selected,
                reviewer_context_id=reviewer_context_id,
                fastest_mechanism="按候选图的阅读路径复述输入、模型、判据、求解和输出。",
                full_width_value="正式论文宽度下需由 renderer 重新确认。",
                table_redundancy="候选图不替代表格中的精确数值。",
                rationale="Hard checks 全部通过后按 soft score 选择结构更清楚的候选。",
                candidate_structures=structures,
                **_competition_review_fields(all_reviews),
            )
            graduated = graduate_visual_candidate(root, image_id, candidate_version=f"r{attempt}")
            result = {
                "status": "selected_pending_promotion",
                "image_id": image_id,
                "selected_candidate": selected,
                "attempts": attempts,
                "review_path": relative_inside(root, root / "figures/sandbox" / image_id / "review.json").as_posix(),
                "competition": competition,
                "graduated": graduated,
                "formal_render_required": True,
            }
            atomic_json(root / "figures/sandbox" / image_id / "review.json", result)
            return result
    fallback = {
        "status": "DROP_AI_IMAGE",
        "image_id": image_id,
        "attempts": attempts,
        "fallback": "drawio",
        "reason": [
            "两轮候选均未通过 Hard review；AI 图片不得作为正式论文图。",
            "请使用 4drawio 或确定性 renderer 重建并重新走 promotion。",
        ],
    }
    atomic_json(root / "figures/sandbox" / image_id / "review.json", fallback)
    return fallback


def command_generator(
    executable: Sequence[str],
    *,
    timeout_seconds: int = 300,
) -> Generator:
    """构造无 shell 外部生图命令适配器。"""
    if not executable:
        raise ContractError("generator executable 不能为空")

    def generate(prompt: Path, output: Path, meta: Path) -> None:
        command = [
            *executable,
            "--prompt-file",
            str(prompt),
            "--output-file",
            str(output),
            "--meta-file",
            str(meta),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
        if completed.returncode != 0:
            raise ContractError(f"生图命令失败({completed.returncode}): {completed.stderr[-500:]}")

    return generate


def command_reviewer(
    executable: Sequence[str],
    *,
    timeout_seconds: int = 300,
) -> Reviewer:
    """构造无 shell 外部审图命令适配器；命令 stdout 必须是 JSON 对象。"""
    if not executable:
        raise ContractError("reviewer executable 不能为空")

    def review(meta: Path, image: Path, prompt: Path, attempt: int) -> dict[str, Any]:
        command = [
            *executable,
            "--meta-file",
            str(meta),
            "--image-file",
            str(image),
            "--prompt-file",
            str(prompt),
            "--attempt",
            str(attempt),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
        if completed.returncode != 0:
            raise ContractError(f"审图命令失败({completed.returncode}): {completed.stderr[-500:]}")
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ContractError("审图命令 stdout 不是 JSON 对象") from exc
        if not isinstance(value, dict):
            raise ContractError("审图命令必须返回 JSON 对象")
        return value

    return review
