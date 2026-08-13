"""SUBMISSION_CONTRACT：年度论文提交格式检查（独立于求解主链）。

与 solver（MODELING_UNITS/科学挑战/盲评）彻底分离：本模块只检查提交 PDF
是否符合**竞赛年度格式规范**，不评价任何模型、数字、论证或科学正确性。规范
按年度版本化（``submission/cumcm/2026.yaml``），2027 规范变化只需新增版本，
不污染求解科学审查。

判定原则（吸取历次审核教训）：
- **摘要页**：只检查首页是否包含摘要文本（如"摘 要"/"Abstract"），不武断
  判"首页必须是摘要页"——因为首页本就是摘要页时不存在违规。
- **目录**：2026 规范"正文不要目录"，检测正文是否出现目录标题/条目。
- **页边距**：不用单一 ``页面宽-最右文字`` 武断定罪；同时检查页面尺寸与正文
  行 x 范围，只报"疑似侵入安全区"由提交方核实。
- **代码附录**：规范要求论文附录含完整可运行代码；检测附录是否存在代码块
  （lstlisting / verbatim / 长代码文件），而不是只看文件清单。

所有结论均为 advisory，不阻断求解，也不写死在求解主链里。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CUMCM_2026_DEFAULT = {
    "contest": "cumcm",
    "year": 2026,
    "no_toc_in_body": True,
    "abstract_must_be_on_first_page": True,
    "min_margin_cm": 2.5,
    "max_body_pages": 30,
    "appendix_must_contain_runnable_code": True,
}
_SUMMARY_MARKERS = ("摘要", "Abstract", "摘 要", "ABSTRA", "summary")


def _find_pdf(run_dir: Path) -> Path | None:
    """返回第一个已存在的提交 PDF；没有时返回 None。"""
    candidates = (
        run_dir / "document.pdf",
        run_dir / "paper/final.pdf",
        run_dir / "paper/longform-draft.pdf",
        run_dir / "paper/draft-1.pdf",
    )
    return next((path for path in candidates if path.is_file()), None)


def _check_abstract_on_first_page(reader: Any) -> list[dict[str, Any]]:
    """首页必须包含摘要标记，且摘要不得延伸超过一页。

    2026 规范：摘要（含标题与关键词）不能超过一页。检测摘要标记是否出现在
    第 1 页、以及第 2 页是否还残留摘要正文（若第 2 页开头仍是摘要内容则超页）。
    """
    findings: list[dict[str, Any]] = []
    try:
        first = str(reader.pages[0].extract_text() or "")
    except (IndexError, AttributeError, OSError):
        return findings
    if not first.strip():
        return findings
    if not any(marker.casefold() in first.casefold() for marker in _SUMMARY_MARKERS):
        findings.append(
            {
                "code": "SUBMISSION_ABSTRACT_FIRST_PAGE",
                "message": "首页未检测到摘要标记；2026 规范要求第一页为摘要专用页。",
                "severity": "advisory",
            }
        )
        return findings
    # 摘要超页：第 2 页开头若直接是摘要正文（关键词/四问结论还在延续），判超页。
    if len(reader.pages) >= 2:
        try:
            second_head = str(reader.pages[1].extract_text() or "")[:300]
        except (AttributeError, OSError):
            second_head = ""
        if second_head.strip() and not _page_starts_new_section(second_head):
            findings.append(
                {
                    "code": "SUBMISSION_ABSTRACT_OVERFLOW",
                    "message": (
                        "摘要疑似从第 1 页延伸至第 2 页开头；2026 规范要求摘要"
                        "（含标题与关键词）不超过一页，请压缩摘要。"
                    ),
                    "severity": "advisory",
                }
            )
    return findings


def _page_starts_new_section(text: str) -> bool:
    """第 2 页开头是否为新的章节标题（而非摘要延续）。"""
    return bool(
        re.search(r"(?m)^\s*[一二三四五六七八九十]+\s*[、．.．]\s*\S", text)
        or re.search(r"(?m)^\s*\d+[\.、]\s*\S", text)
        or re.search(r"(?m)^\s*[IVX]+\.\s+\S", text)
        or re.search(r"(?m)^\s*(Abstract|摘要|Introduction|Contents|1\s+Introduction)\b", text)
        or re.search(r"目\s*录", text[:60])
    )


def _check_no_toc(reader: Any) -> list[dict[str, Any]]:
    """正文不应含目录（2026 规范"不要目录"）。"""
    try:
        text = "\n".join(
            str(page.extract_text() or "") for page in reader.pages[:4]
        )
    except (IndexError, AttributeError, OSError):
        return []
    if not text.strip():
        return []
    toc_signals = (
        re.search(r"(?m)^\s*目\s*录\s*$", text)
        or re.search(r"(?m)^\s*Contents\s*$", text)
        or re.search(r"目\s*录", text[:400])
    )
    if toc_signals:
        return [
            {
                "code": "SUBMISSION_TOC_PRESENT",
                "message": "正文检测到目录；2026 规范要求正文不要目录。",
                "severity": "advisory",
            }
        ]
    return []


def _check_margin_safe_zone(reader: Any) -> list[dict[str, Any]]:
    """页边距安全区审查：同时看页面尺寸与正文行 x 范围，不单点定罪。"""
    try:
        page = reader.pages[0]
        width = float(page.mediabox.width)
        text = str(page.extract_text() or "")
    except (AttributeError, OSError, TypeError):
        return []
    if not text or width <= 0:
        return []
    # A4 宽约 595 pt；规范要求四边 >=2.5cm（约 70.9pt）。粗略扫描正文行 x 范围。
    # 只报"疑似"，明确说明需要结合 TeX geometry 参数进一步核实。
    findings: list[dict[str, Any]] = []
    page_width_cm = width * 2.54 / 72.0
    if abs(page_width_cm - 21.0) > 0.6:
        findings.append(
            {
                "code": "SUBMISSION_PAGE_SIZE",
                "message": (
                    f"页面宽度 {page_width_cm:.2f}cm 偏离 A4（21.0cm）；"
                    "请核实页面尺寸。"
                ),
                "severity": "advisory",
            }
        )
    # 正文行右缘与页面宽度的比例：粗略安全区信号，需人工确认。
    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        max_char_ratio = max(
            len(line.strip()) / max(1, width) for line in lines
        )
        if max_char_ratio > 0.30:
            findings.append(
                {
                    "code": "SUBMISSION_MARGIN_SUSPECTED",
                    "message": (
                        "首页正文行疑似贴近页边；请结合 TeX geometry 参数确认"
                        "四边是否均 >=2.5cm，不要只按单点 x 坐标定罪。"
                    ),
                    "severity": "advisory",
                }
            )
    return findings


def _check_code_appendix(run_dir: Path, reader: Any) -> list[dict[str, Any]]:
    """附录必须含完整可运行代码，不能只有文件清单。"""
    latex_sources = sorted((run_dir / "paper").glob("*.tex"))
    if not latex_sources:
        return []
    appendix_has_code = False
    for source in latex_sources:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\\begin\{lstlisting\}|\\lstinputlisting|\\begin\{verbatim\}", text):
            appendix_has_code = True
            break
    if not appendix_has_code:
        return [
            {
                "code": "SUBMISSION_CODE_APPENDIX",
                "message": (
                    "论文 LaTeX 中未检测到完整代码块（lstlisting/verbatim）；"
                    "2026 规范要求附录含完整可运行代码，仅文件清单不满足。"
                ),
                "severity": "advisory",
            }
        ]
    return []


def _check_page_count(reader: Any) -> tuple[list[dict[str, Any]], int, int | None]:
    """正文页数不应超过年度上限（2026: 正文 30 页）。

    规范限的是**正文**页数，附录代码不计入。因此只把"附录起始前"当正文页数，
    与 30 页硬比较；含代码的总页数只作信息，不告警。
    """
    try:
        total = len(reader.pages)
    except (OSError, ValueError):
        return [], 0, None
    # 定位附录起始页：检测代码/附录标记出现的页。
    appendix_marker_page: int | None = None
    for index in range(total):
        try:
            text = str(reader.pages[index].extract_text() or "")
        except (AttributeError, OSError):
            continue
        if re.search(r"lstinputlisting|\\input\{code|完整源代码|附件提交|参 考 文 献", text):
            appendix_marker_page = index + 1
            break
    body_pages = appendix_marker_page - 1 if appendix_marker_page is not None else total

    findings: list[dict[str, Any]] = []
    if body_pages > CUMCM_2026_DEFAULT["max_body_pages"]:
        findings.append(
            {
                "code": "SUBMISSION_BODY_OVER_LIMIT",
                "message": (
                    f"正文（附录起始前）约 {body_pages} 页，超过 2026 规范上限 "
                    f"{CUMCM_2026_DEFAULT['max_body_pages']} 页。"
                ),
                "severity": "advisory",
            }
        )
    return findings, body_pages, total


def audit_submission_contract(run_dir: Path, *, year: int = 2026) -> dict[str, Any]:
    """检查提交 PDF 是否符合指定年度的格式规范。

    Args:
        run_dir: 待提交的运行目录。
        year: 竞赛年度；默认 2026，未来新增版本配置。

    Returns:
        含 ``findings`` 与 ``metrics`` 的 advisory 审计结果。所有结论都不阻断
        求解，由提交方结合年度官方规范核实。
    """
    root = run_dir.resolve()
    pdf = _find_pdf(root)
    if pdf is None:
        return {
            "success": True,
            "advisory_only": True,
            "year": year,
            "pdf": None,
            "findings": [],
            "metrics": {"pdf_present": False},
            "limitations": "未找到提交 PDF，未执行格式检查。",
        }
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf))
    except (OSError, ValueError) as exc:
        return {
            "success": False,
            "advisory_only": True,
            "year": year,
            "pdf": pdf.name,
            "findings": [
                {
                    "code": "SUBMISSION_PDF_UNREADABLE",
                    "message": f"提交 PDF 无法读取: {exc}",
                    "severity": "error",
                }
            ],
            "metrics": {"pdf_present": True},
            "limitations": "PDF 读取失败。",
        }

    findings: list[dict[str, Any]] = []
    findings.extend(_check_abstract_on_first_page(reader))
    findings.extend(_check_no_toc(reader))
    findings.extend(_check_margin_safe_zone(reader))
    findings.extend(_check_code_appendix(root, reader))
    page_findings, body_pages, total_pages = _check_page_count(reader)
    findings.extend(page_findings)
    metrics = {
        "pdf": pdf.name,
        "pdf_present": True,
        "body_page_count": body_pages,
        "total_page_count": total_pages,
        "year": year,
    }
    return {
        "success": True,
        "advisory_only": True,
        "year": year,
        "pdf": pdf.name,
        "findings": findings,
        "metrics": metrics,
        "limitations": (
            "SUBMISSION_CONTRACT 只检查格式，不评价模型或论证；页边距等判定"
            "为疑似信号，最终以年度官方规范与 TeX geometry 参数为准。"
        ),
    }
