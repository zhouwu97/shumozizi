"""机械提交 QA Adapter；结果只汇入统一 QA Aggregator。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import load_json


def _run_dir_for_pdf(final_pdf: Path, run_id: str) -> Path:
    """从最终 PDF 向上定位运行目录。"""
    run_dir = final_pdf.resolve().parent
    while run_dir.name != run_id and run_dir != run_dir.parent:
        run_dir = run_dir.parent
    return run_dir


def run_mechanical_qa(run_id: str, final_pdf: Path) -> dict[str, Any]:
    """按 RUN_CONFIG_LOCK 中的 Profile 执行页数、匿名和提交包检查。"""
    run_dir = _run_dir_for_pdf(final_pdf, run_id)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        lock = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.json")
        repo_root = run_dir.parents[1]
        profile = load_json(repo_root / lock["competition_profile"]["profile_path"])
        warnings.extend(profile.get("warnings", []))
        if not final_pdf.is_file():
            errors.append("最终 PDF 不存在")
            return _report(errors, warnings)
        reader = PdfReader(str(final_pdf))
        page_limit = profile.get("page_limit")
        if page_limit is not None and len(reader.pages) > page_limit:
            errors.append(f"PDF 页数 {len(reader.pages)} 超过 Profile 上限 {page_limit}")
        page_text = [page.extract_text() or "" for page in reader.pages]
        if any(not text.strip() for text in page_text):
            warnings.append("存在无可提取文本的页面；图形页需结合渲染结果人工复核")
        full_text = "\n".join(page_text)
        caption_pattern = profile["mechanical_qa"]["duplicate_caption_pattern"]
        captions = re.findall(caption_pattern, full_text)
        duplicates = sorted({value for value in captions if captions.count(value) > 1})
        if duplicates:
            errors.append(f"重复 caption 编号: {', '.join(duplicates)}")
        if profile.get("anonymous_required"):
            for pattern in profile["mechanical_qa"]["anonymous_forbidden_patterns"]:
                if re.search(pattern, full_text):
                    errors.append(f"匿名性检查命中: {pattern}")
            metadata = reader.metadata or {}
            author = str(metadata.get("/Author", "")).strip()
            if author:
                errors.append("PDF 元数据包含非空身份字段: /Author")
            creator = str(metadata.get("/Creator", "")).strip().lower()
            if creator and not creator.startswith("typst"):
                warnings.append("PDF /Creator 不是已知排版引擎，请人工确认不含身份信息")
        for required in profile["required_submission_files"]:
            if not (run_dir / required).is_file():
                errors.append(f"提交包缺少文件: {required}")
        if profile["mechanical_qa"].get("require_figure_qa_receipts"):
            figure_files = list((run_dir / "figures").glob("*"))
            for figure in figure_files:
                if figure.is_file() and figure.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}:
                    receipt = figure.with_suffix(figure.suffix + ".qa.json")
                    if not receipt.is_file():
                        errors.append(f"图表缺少 QA 回执: {figure.relative_to(run_dir).as_posix()}")
                    else:
                        payload = load_json(receipt)
                        if payload.get("status") != "pass":
                            errors.append(f"图表 QA 未通过: {figure.name}")
    except Exception as exc:
        errors.append(str(exc))
    return _report(errors, warnings)


def _report(errors: list[str], warnings: list[str]) -> dict[str, Any]:
    """统一 Adapter 报告结构。"""
    return {
        "adapter_id": "mechanical-submission-qa",
        "adapter_version": "1.0.0",
        "status": "pass" if not errors else "blocked",
        "errors": errors,
        "warnings": warnings,
    }
