"""验证提交包物化按竞赛交付配置解耦 DOCX。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.profiles.delivery import delivery_requirements_for_competition
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review import materialize_submission_package


def _run(tmp_path: Path, competition: str = "cumcm") -> Path:
    """创建带非空 PDF 的最小 v3.1 运行。"""
    run_dir = initialize_simple_run(
        tmp_path, "delivery", competition=competition, required_questions=["Q1"]
    )
    (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nfixture\n")
    return run_dir


def test_default_delivery_requires_pdf_only(tmp_path: Path) -> None:
    """内置 Profile 及未识别竞赛默认只强制 PDF、Word 可选。"""
    assert delivery_requirements_for_competition("cumcm") == {
        "pdf_required": True,
        "docx_required": False,
    }
    assert delivery_requirements_for_competition("") == {
        "pdf_required": True,
        "docx_required": False,
    }
    assert delivery_requirements_for_competition("未知竞赛占位") == {
        "pdf_required": True,
        "docx_required": False,
    }


def test_pdf_only_submission_when_docx_absent(tmp_path: Path) -> None:
    """docx_required=false 时缺少 Word 不阻断物化，产出纯 PDF 提交包。"""
    run_dir = _run(tmp_path)

    manifest = materialize_submission_package(run_dir)

    roles = {item["role"] for item in manifest["files"]}
    assert roles == {"final_pdf"}
    assert not (run_dir / "paper" / "submission" / "final.docx").is_file()


def test_present_docx_is_included_even_when_optional(tmp_path: Path) -> None:
    """Word 存在时仍纳入提交包，pandoc 可用的场合不丢失 Word 版本。"""
    run_dir = _run(tmp_path)
    (run_dir / "paper" / "final.docx").write_bytes(b"PK\x03\x04docx-stub")

    manifest = materialize_submission_package(run_dir)

    roles = {item["role"] for item in manifest["files"]}
    assert "final_docx" in roles
    assert (run_dir / "paper" / "submission" / "final.docx").is_file()


def test_stale_docx_is_cleaned_when_it_disappears(tmp_path: Path) -> None:
    """先前登记的 Word 副本在 Word 消失后必须从提交目录移除，不留未登记文件。"""
    run_dir = _run(tmp_path)
    docx = run_dir / "paper" / "final.docx"
    docx.write_bytes(b"PK\x03\x04docx-stub")
    materialize_submission_package(run_dir)
    assert (run_dir / "paper" / "submission" / "final.docx").is_file()

    docx.unlink()
    manifest = materialize_submission_package(run_dir)

    assert {item["role"] for item in manifest["files"]} == {"final_pdf"}
    assert not (run_dir / "paper" / "submission" / "final.docx").is_file()
