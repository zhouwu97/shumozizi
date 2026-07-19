"""从 sealed result 生成论文实值，并在源文件与最终 PDF 中复验。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.results.metrics import evaluate_expression
from shumozizi.results.sealing import verify_sealed_result


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _active_result(run_dir: Path, result_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取仍可用于论文的注册项及 sealed result。"""
    registry = load_json(run_dir / "results" / "result_registry.json")
    require_valid(registry, "result_registry")
    item = next((entry for entry in registry["results"] if entry["result_id"] == result_id), None)
    if item is None or item["status"] != "accepted" or item["paper_allowed"] is not True:
        raise ContractError(f"论文证据引用了 revoked、未接受或禁止使用的结果: {result_id}")
    verification = verify_sealed_result(run_dir, result_id)
    if not verification["valid"]:
        raise ContractError(
            f"sealed result 复验失败 {result_id}: {'; '.join(verification['errors'])}"
        )
    return item, load_json(run_dir / item["sealed_result_path"])


def _claim_value(run_dir: Path, claim: dict[str, Any]) -> tuple[Any, str]:
    """从一个或多个 sealed 指标计算 claim 展示值。"""
    values: dict[str, Any] = {}
    units: set[str] = set()
    for source in claim["inputs"]:
        _, sealed = _active_result(run_dir, source["result_id"])
        metric = next(
            (
                item
                for item in sealed["metrics"]
                if item["metric_spec_id"] == source["metric_spec_id"]
            ),
            None,
        )
        if metric is None:
            raise ContractError(f"证据字段不存在: {source['metric_spec_id']}")
        values[source["name"]] = metric["value"]
        units.add(metric["unit"])
    value = (
        evaluate_expression(claim["expression"], values)
        if claim.get("expression")
        else next(iter(values.values()))
    )
    display = claim["display"]
    value = value * display.get("scale", 1)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError("论文展示值必须是数值")
    unit = display.get("unit") or (next(iter(units)) if len(units) == 1 else "")
    return value, unit


def generate_paper_evidence(run_dir: Path) -> dict[str, str]:
    """生成论文唯一允许调用的 Typst evidence macro 数据。"""
    evidence_map = load_json(run_dir / "paper" / "evidence_map.json")
    require_valid(evidence_map, "evidence_map")
    if evidence_map["run_id"] != run_dir.name:
        raise ContractError("evidence_map.run_id 与运行目录不一致")
    rendered: dict[str, str] = {}
    for claim in evidence_map["claims"]:
        value, unit = _claim_value(run_dir, claim)
        decimals = claim["display"]["decimals"]
        rendered[claim["claim_id"]] = f"{value:.{decimals}f}{(' ' + unit) if unit else ''}"
    lines = ["// 此文件由 generate_paper_evidence.py 生成，禁止手改。", "#let evidence_values = ("]
    lines.extend(f'  "{key}": "{value}",' for key, value in sorted(rendered.items()))
    lines.extend(
        [
            ")",
            "#let evidence(id) = {",
            "  let value = evidence_values.at(id)",
            "  [EVIDENCE:#id #value]",
            "}",
            "",
        ]
    )
    path = run_dir / "paper" / "generated" / "evidence_values.typ"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".typ.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
    return rendered


def validate_evidence(run_dir: Path, final_pdf: Path) -> dict[str, Any]:
    """校验 evidence map、Typst 调用、生成哈希与 PDF 邻近实值。"""
    repo_root = run_dir.resolve().parents[1]
    errors: list[str] = []
    try:
        verify_run_config_lock(repo_root, run_dir)
        expected = generate_paper_evidence(run_dir)
        evidence_map = load_json(run_dir / "paper" / "evidence_map.json")
        source_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((run_dir / "paper").rglob("*.typ"))
            if "generated" not in path.parts
        )
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(final_pdf)).pages)
        for claim in evidence_map["claims"]:
            claim_id = claim["claim_id"]
            if f'#evidence("{claim_id}")' not in source_text:
                errors.append(f"论文源缺少 claim macro: {claim_id}")
            marker = f"EVIDENCE:{claim_id}"
            position = pdf_text.find(marker)
            if (
                position < 0
                or expected[claim_id]
                not in pdf_text[position : position + len(marker) + len(expected[claim_id]) + 80]
            ):
                errors.append(f"PDF 中 claim 标签附近找不到期望实值: {claim_id}")
        if any(
            claim.get("core") and f'#evidence("{claim["claim_id"]}")' not in source_text
            for claim in evidence_map["claims"]
        ):
            errors.append("摘要核心 claim 缺少映射")
    except Exception as exc:
        errors.append(str(exc))
        expected = {}
    generated_path = run_dir / "paper" / "generated" / "evidence_values.typ"
    report = {
        "schema_name": "evidence_validation_report",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "status": "pass" if not errors else "blocked",
        "final_pdf_path": final_pdf.resolve().relative_to(run_dir.resolve()).as_posix()
        if final_pdf.is_file()
        else str(final_pdf),
        "final_pdf_sha256": sha256_file(final_pdf) if final_pdf.is_file() else None,
        "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json"),
        "evidence_map_sha256": sha256_file(run_dir / "paper" / "evidence_map.json")
        if (run_dir / "paper" / "evidence_map.json").is_file()
        else None,
        "generated_evidence_sha256": sha256_file(generated_path)
        if generated_path.is_file()
        else None,
        "rendered_values": expected,
        "errors": errors,
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / "review" / "EVIDENCE_VALIDATION.json", report)
    return report
