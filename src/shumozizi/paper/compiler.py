"""受控编译 v3 论文并冻结可复验的 LaTeX/Typst 回执。"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.paper.templates import MANIFEST_PATH, require_materialized_template
from shumozizi.simple.state import read_simple_state, utc_now

COMPILE_RECEIPT_PATH = Path("paper/compile-receipt.json")
_GENERATED_PAPER_FILES = {
    "compile-receipt.json",
    "final.pdf",
    "main.pdf",
    "main.aux",
    "main.bbl",
    "main.bcf",
    "main.blg",
    "main.fdb_latexmk",
    "main.fls",
    "main.idx",
    "main.ilg",
    "main.ind",
    "main.lof",
    "main.log",
    "main.lot",
    "main.nav",
    "main.out",
    "main.run.xml",
    "main.snm",
    "main.synctex.gz",
    "main.toc",
    "main.vrb",
    "main.xdv",
}


def _schema() -> dict[str, Any]:
    """读取论文编译回执的 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "simple_paper_compile_receipt.schema.json")


def _require_schema(payload: dict[str, Any]) -> None:
    """校验编译回执的结构。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("论文编译回执不符合协议: " + "; ".join(errors))


def _paper_source_sha256(paper_dir: Path) -> str:
    """计算论文实际输入树的摘要，排除编译输出和本身的回执。"""
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in paper_dir.rglob("*")
        if path.is_file() and path.relative_to(paper_dir).as_posix() not in _GENERATED_PAPER_FILES
    )
    for path in files:
        digest.update(path.relative_to(paper_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _compiler_steps(engine: str) -> tuple[str, list[list[str]]]:
    """选择已安装的编译器并构造不经 shell 的受控命令。"""
    if engine == "typst":
        command = shutil.which("typst")
        if command is None:
            raise ContractError("模板选择了 Typst，但当前环境未检测到 typst")
        return "typst", [[command, "compile", "main.typ", "final.pdf"]]

    latexmk = shutil.which("latexmk")
    if latexmk is not None:
        return "latexmk", [
            [
                latexmk,
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "main.tex",
            ]
        ]
    xelatex = shutil.which("xelatex")
    if xelatex is not None:
        command = [xelatex, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        return "xelatex", [command, command]
    tectonic = shutil.which("tectonic")
    if tectonic is not None:
        return "tectonic", [[tectonic, "--keep-logs", "--keep-intermediates", "main.tex"]]
    pdflatex = shutil.which("pdflatex")
    if pdflatex is not None:
        command = [pdflatex, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        return "pdflatex", [command, command]
    raise ContractError("模板选择了 LaTeX，但未检测到 latexmk/xelatex/tectonic/pdflatex")


def _run_compiler_steps(
    paper_dir: Path, steps: list[list[str]], *, timeout_seconds: int
) -> list[dict[str, Any]]:
    """执行所有编译命令并只冻结其最小机器输出。"""
    executions: list[dict[str, Any]] = []
    for command in steps:
        try:
            completed = subprocess.run(
                command,
                cwd=paper_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ContractError(f"论文编译超时（{timeout_seconds} 秒）: {command[0]}") from exc
        except OSError as exc:
            raise ContractError(f"无法启动论文编译器 {command[0]}: {exc}") from exc
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip().replace("\n", " ")[:800]
            raise ContractError(f"论文编译失败（{command[0]}，退出码 {completed.returncode}）: {message}")
        executions.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
            }
        )
    return executions


def _require_pdf(path: Path) -> None:
    """拒绝编译器零退出却未得到有效 PDF 的情况。"""
    if not path.is_file() or path.stat().st_size < 8:
        raise ContractError("论文编译没有产生非空 PDF")
    if not path.read_bytes().startswith(b"%PDF"):
        raise ContractError("论文编译输出不是有效 PDF 文件头")


def compile_paper(run_dir: Path, *, timeout_seconds: int = 300) -> dict[str, Any]:
    """按模板清单编译论文，优先执行已选择的 LaTeX 引擎。

    Args:
        run_dir: 当前 v3 运行目录。
        timeout_seconds: 单次编译命令允许的最长秒数。

    Returns:
        已写入 ``paper/compile-receipt.json`` 的冻结编译收据。

    Raises:
        ContractError: 模板、编译器、输入或输出不满足受控编译边界。
    """
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("论文编译 timeout_seconds 必须在 1 至 3600 之间")
    state = read_simple_state(run_dir)
    manifest = require_materialized_template(run_dir)
    root = run_dir.resolve()
    paper_dir = root / "paper"
    entrypoint = paper_dir / manifest["question_layout"]["entrypoint_path"]
    if not entrypoint.is_file():
        raise ContractError("论文模板入口缺失，不能编译")
    source_sha256 = _paper_source_sha256(paper_dir)
    compiler, steps = _compiler_steps(manifest["engine"])
    executions = _run_compiler_steps(paper_dir, steps, timeout_seconds=timeout_seconds)

    compiled_pdf = paper_dir / ("final.pdf" if manifest["engine"] == "typst" else "main.pdf")
    _require_pdf(compiled_pdf)
    final_pdf = paper_dir / "final.pdf"
    if compiled_pdf != final_pdf:
        shutil.copy2(compiled_pdf, final_pdf)
    _require_pdf(final_pdf)
    if _paper_source_sha256(paper_dir) != source_sha256:
        raise ContractError("论文源文件在编译期间发生变化，拒绝冻结不稳定产物")

    manifest_path = root / MANIFEST_PATH
    receipt = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "template_manifest_path": MANIFEST_PATH.as_posix(),
        "template_manifest_sha256": sha256_file(manifest_path),
        "engine": manifest["engine"],
        "requested_engine": manifest.get("requested_engine", manifest["engine"]),
        "fallback_used": manifest["fallback_used"],
        "fallback_reason": manifest.get("fallback_reason"),
        "compiler": compiler,
        "entrypoint_path": entrypoint.relative_to(root).as_posix(),
        "entrypoint_sha256": sha256_file(entrypoint),
        "paper_source_sha256": source_sha256,
        "final_pdf_path": "paper/final.pdf",
        "final_pdf_sha256": sha256_file(final_pdf),
        "executions": executions,
        "generated_at": utc_now(),
    }
    _require_schema(receipt)
    atomic_json(root / COMPILE_RECEIPT_PATH, receipt)
    return receipt


def verify_paper_compile_receipt(run_dir: Path) -> dict[str, Any]:
    """复验当前 PDF 确由已冻结的模板输入和受控编译生成。"""
    errors: list[str] = []
    root = run_dir.resolve()
    receipt_path = root / COMPILE_RECEIPT_PATH
    try:
        receipt = load_json(receipt_path)
        _require_schema(receipt)
        state = read_simple_state(root)
        manifest = require_materialized_template(root)
        if receipt["run_id"] != state["run_id"]:
            errors.append("编译回执 run_id 与当前运行不一致")
        manifest_path = root / MANIFEST_PATH
        if receipt["template_manifest_sha256"] != sha256_file(manifest_path):
            errors.append("编译回执未绑定当前模板清单")
        for key in ("engine", "requested_engine", "fallback_used", "fallback_reason"):
            expected = manifest.get(key, manifest["engine"] if key == "requested_engine" else None)
            if receipt[key] != expected:
                errors.append(f"编译回执 {key} 与模板清单不一致")
        entrypoint = root / receipt["entrypoint_path"]
        # question_layout 中的入口路径相对于 paper/，回执中则相对于 run 根目录。
        # 两者必须在各自的声明域内解析，不能把正确的 main.tex/main.typ 误判为漂移。
        expected_entry = root / "paper" / manifest["question_layout"]["entrypoint_path"]
        if entrypoint.resolve() != expected_entry.resolve() or not entrypoint.is_file():
            errors.append("编译回执入口与当前模板不一致")
        elif receipt["entrypoint_sha256"] != sha256_file(entrypoint):
            errors.append("论文入口在编译后已变化")
        if receipt["paper_source_sha256"] != _paper_source_sha256(root / "paper"):
            errors.append("论文源文件在编译后已变化")
        final_pdf = root / receipt["final_pdf_path"]
        try:
            _require_pdf(final_pdf)
            if receipt["final_pdf_sha256"] != sha256_file(final_pdf):
                errors.append("最终 PDF 在编译后已变化")
        except ContractError as exc:
            errors.append(str(exc))
    except (ContractError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}
