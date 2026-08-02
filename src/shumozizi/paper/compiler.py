"""受控编译 v3 论文并冻结可复验的 LaTeX/Typst 回执。"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.paper.docx_qa import audit_docx
from shumozizi.paper.templates import MANIFEST_PATH, require_materialized_template
from shumozizi.simple.state import read_simple_state, utc_now

COMPILE_RECEIPT_PATH = Path("paper/compile-receipt.json")
REVIEWABLE_DRAFT_RECEIPT_PATH = Path("paper/reviewable-draft-receipt.json")
LONGFORM_DRAFT_RECEIPT_PATH = Path("paper/longform-draft-receipt.json")
_REVIEWABLE_DRAFT_STATUS_PATHS = {
    "latex": Path("paper/generated/reviewable-draft-status.tex"),
    "typst": Path("paper/generated/reviewable-draft-status.typ"),
}
_LONGFORM_DRAFT_STATUS_PATHS = {
    "latex": Path("paper/generated/longform-draft-status.tex"),
    "typst": Path("paper/generated/longform-draft-status.typ"),
}
_REVIEWABLE_DRAFT_ENTRYPOINTS = {
    "latex": Path("paper/reviewable-draft.tex"),
    "typst": Path("paper/reviewable-draft.typ"),
}
_LONGFORM_DRAFT_ENTRYPOINTS = {
    "latex": Path("paper/longform-draft.tex"),
    "typst": Path("paper/longform-draft.typ"),
}
_LONGFORM_AUTHOR_SOURCES = {
    "latex": Path("paper/longform-source.tex"),
    "typst": Path("paper/longform-source.typ"),
}
_GENERATED_PAPER_FILES = {
    "compile-receipt.json",
    "final.pdf",
    "final.docx",
    "draft-1.pdf",
    "reviewable-draft-receipt.json",
    "reviewable-draft.tex",
    "reviewable-draft.typ",
    "reviewable-draft.pdf",
    "longform-draft-receipt.json",
    "longform-draft.tex",
    "longform-draft.typ",
    "longform-draft.pdf",
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
_GENERATED_PAPER_SUFFIXES = (
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".idx",
    ".ilg",
    ".ind",
    ".lof",
    ".log",
    ".lot",
    ".nav",
    ".out",
    ".run.xml",
    ".snm",
    ".synctex.gz",
    ".toc",
    ".vrb",
    ".xdv",
)


def _atomic_text(path: Path, value: str) -> None:
    """在同目录写入临时文件后原子替换文本产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


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
        if path.is_file()
        and path.relative_to(paper_dir).as_posix() not in _GENERATED_PAPER_FILES
        # LaTeX 的 \include 会在章节目录生成同名 .aux；这些是编译输出，不是源文件漂移。
        and not path.name.endswith(_GENERATED_PAPER_SUFFIXES)
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
    # latexmk 是 Perl 脚本包装器；MiKTeX 只安装了可执行入口而缺少 Perl 时，
    # 直接调用它会阻断本可由 XeLaTeX 完成的受控双次编译。
    if latexmk is not None and shutil.which("perl") is not None:
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
        command = [
            xelatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "main.tex",
        ]
        return "xelatex", [command, command]
    tectonic = shutil.which("tectonic")
    if tectonic is not None:
        return "tectonic", [[tectonic, "--keep-logs", "--keep-intermediates", "main.tex"]]
    pdflatex = shutil.which("pdflatex")
    if pdflatex is not None:
        command = [
            pdflatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "main.tex",
        ]
        return "pdflatex", [command, command]
    raise ContractError("模板选择了 LaTeX，但未检测到 latexmk/xelatex/tectonic/pdflatex")


def _extract_latex_errors(paper_dir: Path) -> str:
    """从 main.log 提取 LaTeX 的 '! Error' 行，辅助失败诊断。

    xelatex/pdflatex/latexmk 把真实错误写入 main.log 而非 stderr；
    仅在编译失败后调用，最多返回前 5 条错误行，不超过 400 字符。
    """
    log_path = paper_dir / "main.log"
    if not log_path.is_file():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    error_lines = [line for line in lines if line.startswith("! ")][:5]
    if not error_lines:
        return ""
    return " | ".join(error_lines)[:400]


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
            # LaTeX 把真实错误写入 main.log，stderr/stdout 通常近空；优先从日志提取。
            log_snippet = _extract_latex_errors(paper_dir)
            stream_snippet = (completed.stderr or completed.stdout).strip().replace("\n", " ")[:400]
            detail = log_snippet or stream_snippet
            raise ContractError(
                f"论文编译失败（{command[0]}，退出码 {completed.returncode}）: {detail}"
            )
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


def _require_text_list(name: str, values: list[str]) -> list[str]:
    """校验草稿披露字段，拒绝空白或非字符串条目。"""
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ContractError(f"可审阅草稿的 {name} 必须是非空字符串数组")
    return [value.strip() for value in values]


def _latex_escape(value: str) -> str:
    """转义草稿状态页中的普通文本，避免披露内容破坏 LaTeX。"""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _render_reviewable_disclosure(
    *,
    engine: str,
    completed_content: list[str],
    unfinished_questions: list[str],
    remaining_experiments: list[str],
    provisional_conclusions: list[str],
) -> str:
    """生成会被实际编入首版 PDF 的状态披露页。"""
    sections = (
        ("当前已完成内容", completed_content),
        ("暂未完成的问题", unfinished_questions),
        ("仍需补的实验", remaining_experiments),
        ("当前候选结论", provisional_conclusions),
    )
    if engine == "latex":
        lines = [
            r"\clearpage",
            r"\section*{可审阅草稿状态说明}",
            r"\textbf{本稿不可作为最终提交。}",
        ]
        for heading, items in sections:
            lines.extend([rf"\subsection*{{{heading}}}", r"\begin{itemize}"])
            visible = items or ["暂无；该项尚未形成可由当前真实证据支持的内容。"]
            lines.extend(rf"\item {_latex_escape(item)}" for item in visible)
            lines.append(r"\end{itemize}")
        return "\n".join(lines) + "\n"
    lines = [
        "#pagebreak()",
        "= 可审阅草稿状态说明",
        "*本稿不可作为最终提交。*",
    ]
    for heading, items in sections:
        lines.append(f"== {heading}")
        visible = items or ["暂无；该项尚未形成可由当前真实证据支持的内容。"]
        lines.extend(f"- {item}" for item in visible)
    return "\n".join(lines) + "\n"


def _draft_steps(
    engine: str, entrypoint_name: str, *, output_name: str = "reviewable-draft.pdf"
) -> tuple[str, list[list[str]]]:
    """把正式编译器命令改写为独立草稿入口，保持测试和工具探测兼容。"""
    compiler, steps = _compiler_steps(engine)
    rewritten: list[list[str]] = []
    for command in steps:
        rewritten.append(
            [
                entrypoint_name
                if item in {"main.tex", "main.typ"}
                else output_name
                if item == "final.pdf"
                else item
                for item in command
            ]
        )
    return compiler, rewritten


def _render_longform_status(*, engine: str) -> str:
    """生成长篇科学首稿的轻量状态页，不把运行控制信息写入正文。"""
    if engine == "latex":
        return (
            r"\clearpage\section*{长篇科学首稿状态说明}" + "\n"
            r"\textbf{本稿用于完整论证与独立冷读，不是最终提交稿。}" + "\n"
            r"本稿保留研究材料池和故事板中的完整推导、结构观察、机制与边界，" + "\n"
            r"后续由编辑审阅其篇幅、叙事和视觉取舍。" + "\n"
        )
    return (
        "#pagebreak()\n= 长篇科学首稿状态说明\n"
        "*本稿用于完整论证与独立冷读，不是最终提交稿。*\n"
        "本稿保留研究材料池和故事板中的完整推导、结构观察、机制与边界，"
        "后续由编辑审阅其篇幅、叙事和视觉取舍。\n"
    )


def compile_longform_draft(
    run_dir: Path,
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """编译默认的长篇科学首稿。

    长篇首稿要求科学输入和素材/故事板可复验，但不要求竞争稿的最终盲审、版式
    或篇幅门禁；它是完整展开论证的中间产物，不能被 ``compile_paper`` 当作最终稿。
    """
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("论文编译 timeout_seconds 必须在 1 至 3600 之间")
    from shumozizi.simple.authoring import require_internal_authoring

    require_internal_authoring(run_dir)
    from shumozizi.paper.author_pass import (
        AUTHOR_PASS_MANIFEST_PATH,
        require_author_pass,
        require_scientific_authoring_ready,
    )

    require_scientific_authoring_ready(run_dir)
    author_pass = require_author_pass(run_dir)
    manifest = require_materialized_template(run_dir)
    engine = manifest["engine"]
    root = run_dir.resolve()
    paper_dir = root / "paper"
    author_source_relative = _LONGFORM_AUTHOR_SOURCES[engine]
    author_source = root / author_source_relative
    if not author_source.is_file() or author_source.stat().st_size == 0:
        raise ContractError(
            f"Author Pass 尚未生成 {author_source_relative.as_posix()}，不能把正式入口冒充长篇首稿"
        )
    formal_entrypoint = paper_dir / manifest["question_layout"]["entrypoint_path"]
    if formal_entrypoint.is_file() and formal_entrypoint.read_text(
        encoding="utf-8"
    ) == author_source.read_text(encoding="utf-8"):
        raise ContractError("longform-source 与正式入口完全相同，尚未完成真实 Author Pass")
    status_relative = _LONGFORM_DRAFT_STATUS_PATHS[engine]
    status_path = root / status_relative
    _atomic_text(status_path, _render_longform_status(engine=engine))
    entry_relative = _LONGFORM_DRAFT_ENTRYPOINTS[engine]
    draft_entrypoint = root / entry_relative
    source = author_source.read_text(encoding="utf-8")
    if engine == "latex":
        marker = r"\end{document}"
        if marker not in source:
            raise ContractError("LaTeX 模板缺少 \\end{document}，无法插入长篇首稿状态页")
        draft_source = source.replace(
            marker,
            r"\input{generated/longform-draft-status.tex}" + "\n" + marker,
            1,
        )
    else:
        draft_source = source + '\n#include("generated/longform-draft-status.typ")\n'
    _atomic_text(draft_entrypoint, draft_source)
    source_sha256 = sha256_file(author_source)
    compiler, steps = _draft_steps(engine, draft_entrypoint.name, output_name="longform-draft.pdf")
    executions = _run_compiler_steps(paper_dir, steps, timeout_seconds=timeout_seconds)
    artifact = paper_dir / "longform-draft.pdf"
    _require_pdf(artifact)
    from shumozizi.paper.page_budget import PAGE_BUDGET_PATH, audit_page_budget

    page_budget = audit_page_budget(root, artifact, enforce_minimum=False)
    receipt = {
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "draft_mode": "longform_scientific_draft",
        "artifact_path": "paper/longform-draft.pdf",
        "artifact_sha256": sha256_file(artifact),
        "entrypoint_path": entry_relative.as_posix(),
        "entrypoint_sha256": sha256_file(draft_entrypoint),
        "author_source_path": author_source_relative.as_posix(),
        "author_source_sha256": source_sha256,
        "author_pass_manifest_path": AUTHOR_PASS_MANIFEST_PATH.as_posix(),
        "author_pass_manifest_sha256": sha256_file(root / AUTHOR_PASS_MANIFEST_PATH),
        "status_path": status_relative.as_posix(),
        "status_sha256": sha256_file(status_path),
        "template_manifest_sha256": sha256_file(root / MANIFEST_PATH),
        "paper_source_sha256": source_sha256,
        "research_package_sha256": author_pass["research_package"]["sha256"],
        "author_brief_sha256": author_pass["author_brief"]["sha256"],
        "page_budget_path": PAGE_BUDGET_PATH.as_posix(),
        "page_budget_sha256": sha256_file(root / PAGE_BUDGET_PATH),
        "page_count": page_budget["page_count"],
        "page_budget_status": page_budget["status"],
        "compiler": compiler,
        "executions": executions,
        "not_for_final_submission": True,
        "generated_at": utc_now(),
    }
    from shumozizi.paper.policy import formal_result_digest, policy_fingerprint

    receipt["formal_result_digest"] = formal_result_digest(root)
    from shumozizi.core.repo_root import resolve_repo_root

    repo_root = resolve_repo_root(Path(__file__))
    receipt["paper_policy_fingerprint"] = policy_fingerprint(repo_root, "paper")
    receipt["visual_policy_fingerprint"] = policy_fingerprint(repo_root, "visual")
    atomic_json(root / LONGFORM_DRAFT_RECEIPT_PATH, receipt)
    return receipt


def verify_longform_draft_receipt(run_dir: Path) -> dict[str, Any]:
    """复验长篇首稿仍绑定当前模板、状态页和 PDF。"""
    root = run_dir.resolve()
    receipt_path = root / LONGFORM_DRAFT_RECEIPT_PATH
    errors: list[str] = []
    try:
        receipt = load_json(receipt_path)
        if receipt.get("draft_mode") != "longform_scientific_draft":
            errors.append("长篇首稿回执 draft_mode 无效")
        for path_key, hash_key, label in (
            ("artifact_path", "artifact_sha256", "长篇首稿 PDF"),
            ("entrypoint_path", "entrypoint_sha256", "长篇首稿入口"),
            ("status_path", "status_sha256", "长篇首稿状态页"),
        ):
            path = root / receipt[path_key]
            if not path.is_file() or receipt.get(hash_key) != sha256_file(path):
                errors.append(f"{label}缺失或已变化")
        _require_pdf(root / receipt["artifact_path"])
        if receipt.get("template_manifest_sha256") != sha256_file(root / MANIFEST_PATH):
            errors.append("长篇首稿未绑定当前模板清单")
        if receipt.get("author_source_path"):
            source = root / receipt["author_source_path"]
            if not source.is_file() or receipt.get("author_source_sha256") != sha256_file(source):
                errors.append("长篇首稿未绑定当前 Author 源文件")
            from shumozizi.paper.author_pass import require_author_pass

            author_pass = require_author_pass(root)
            manifest_path = root / receipt["author_pass_manifest_path"]
            if receipt.get("author_pass_manifest_sha256") != sha256_file(manifest_path):
                errors.append("长篇首稿未绑定当前 Author Pass manifest")
            if receipt.get("research_package_sha256") != author_pass["research_package"]["sha256"]:
                errors.append("长篇首稿未绑定当前 Research Package")
            if receipt.get("author_brief_sha256") != author_pass["author_brief"]["sha256"]:
                errors.append("长篇首稿未绑定当前 Author Brief")
        else:
            # 旧回执继续按 Material Pool 与 Storyboard 复验。
            for relative, key in (
                ("paper/generated/material_pool.json", "material_pool_sha256"),
                ("paper/generated/research_storyboard.json", "storyboard_sha256"),
            ):
                if receipt.get(key) != sha256_file(root / relative):
                    errors.append(f"长篇首稿未绑定当前 {relative}")
        from shumozizi.paper.page_budget import verify_page_budget

        page_budget = verify_page_budget(root, pdf_path=root / receipt["artifact_path"])
        if not page_budget["valid"]:
            errors.extend(page_budget["errors"])
        if receipt.get("page_budget_sha256") != sha256_file(root / page_budget["report_path"]):
            errors.append("长篇首稿页数审计回执已变化")
    except (ContractError, KeyError, OSError, ValueError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}


def compile_reviewable_draft(
    run_dir: Path,
    *,
    completed_content: list[str],
    unfinished_questions: list[str],
    remaining_experiments: list[str],
    provisional_conclusions: list[str],
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """在正式答案尚未全部合格时编译带显式披露的首版草稿。

    该入口只放宽正式答案、科学挑战和图表闭环门禁，不放宽模板、编译器、
    PDF 有效性和来源绑定。调用方只能写已有内容；没有真实证据支持的候选结论
    应保持为空，函数会在披露页明确显示“暂无”，而不会补造数字或结论。

    Args:
        run_dir: 当前 v3.2 运行目录。
        completed_content: 已完成且可供审阅的内容说明。
        unfinished_questions: 尚未完成的必答问题 ID。
        remaining_experiments: 仍需真实执行的实验说明。
        provisional_conclusions: 由当前真实证据支持、但尚未冻结的候选结论。
        timeout_seconds: 单次编译命令允许的最长秒数。

    Returns:
        已写入独立草稿回执的内容。

    Raises:
        ContractError: 披露、模板、编译器或 PDF 产物不满足草稿边界。
    """
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("论文编译 timeout_seconds 必须在 1 至 3600 之间")
    completed = _require_text_list("completed_content", completed_content)
    unfinished = _require_text_list("unfinished_questions", unfinished_questions)
    remaining = _require_text_list("remaining_experiments", remaining_experiments)
    provisional = _require_text_list("provisional_conclusions", provisional_conclusions)
    state = read_simple_state(run_dir)
    unknown_questions = sorted(set(unfinished) - set(state["required_questions"]))
    if unknown_questions:
        raise ContractError("草稿未完成问题不属于必答问题: " + ", ".join(unknown_questions))
    from shumozizi.paper.readiness import require_reviewable_draft_argument_readiness

    require_reviewable_draft_argument_readiness(run_dir, unfinished_questions=unfinished)
    manifest = require_materialized_template(run_dir)
    engine = manifest["engine"]
    root = run_dir.resolve()
    paper_dir = root / "paper"
    formal_entrypoint = paper_dir / manifest["question_layout"]["entrypoint_path"]
    if not formal_entrypoint.is_file():
        raise ContractError("论文模板入口缺失，不能编译可审阅草稿")
    status_relative = _REVIEWABLE_DRAFT_STATUS_PATHS[engine]
    status_path = root / status_relative
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_text = _render_reviewable_disclosure(
        engine=engine,
        completed_content=completed,
        unfinished_questions=unfinished,
        remaining_experiments=remaining,
        provisional_conclusions=provisional,
    )
    _atomic_text(status_path, status_text)
    entry_relative = _REVIEWABLE_DRAFT_ENTRYPOINTS[engine]
    draft_entrypoint = root / entry_relative
    source = formal_entrypoint.read_text(encoding="utf-8")
    if engine == "latex":
        marker = r"\end{document}"
        if marker not in source:
            raise ContractError("LaTeX 模板缺少 \\end{document}，无法插入草稿披露页")
        draft_source = source.replace(
            marker,
            r"\input{generated/reviewable-draft-status.tex}" + "\n" + marker,
            1,
        )
    else:
        draft_source = source + '\n#include("generated/reviewable-draft-status.typ")\n'
    _atomic_text(draft_entrypoint, draft_source)
    source_sha256 = _paper_source_sha256(paper_dir)
    compiler, steps = _draft_steps(engine, draft_entrypoint.name)
    executions = _run_compiler_steps(paper_dir, steps, timeout_seconds=timeout_seconds)
    compiled_pdf = paper_dir / "reviewable-draft.pdf"
    _require_pdf(compiled_pdf)
    artifact = paper_dir / "draft-1.pdf"
    shutil.copy2(compiled_pdf, artifact)
    _require_pdf(artifact)
    receipt = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "artifact_path": "paper/draft-1.pdf",
        "artifact_sha256": sha256_file(artifact),
        "entrypoint_path": entry_relative.as_posix(),
        "entrypoint_sha256": sha256_file(draft_entrypoint),
        "status_path": status_relative.as_posix(),
        "status_sha256": sha256_file(status_path),
        "template_manifest_sha256": sha256_file(root / MANIFEST_PATH),
        "paper_source_sha256": source_sha256,
        "compiler": compiler,
        "executions": executions,
        "disclosure": {
            "completed_content": completed,
            "unfinished_questions": unfinished,
            "remaining_experiments": remaining,
            "provisional_conclusions": provisional,
        },
        "not_for_final_submission": True,
        "generated_at": utc_now(),
    }
    atomic_json(root / REVIEWABLE_DRAFT_RECEIPT_PATH, receipt)
    from shumozizi.simple.delivery import freeze_pdf_milestone

    freeze_pdf_milestone(root, "first_reviewable")
    return receipt


def verify_reviewable_draft_receipt(run_dir: Path) -> dict[str, Any]:
    """复验首版草稿、披露页、草稿入口与独立回执仍相互绑定。"""
    root = run_dir.resolve()
    receipt_path = root / REVIEWABLE_DRAFT_RECEIPT_PATH
    errors: list[str] = []
    try:
        receipt = load_json(receipt_path)
        if receipt.get("run_id") != read_simple_state(root)["run_id"]:
            errors.append("草稿编译回执 run_id 与当前运行不一致")
        if receipt.get("not_for_final_submission") is not True:
            errors.append("草稿编译回执没有明确禁止最终提交")
        for path_key, hash_key, label in (
            ("artifact_path", "artifact_sha256", "草稿 PDF"),
            ("entrypoint_path", "entrypoint_sha256", "草稿入口"),
            ("status_path", "status_sha256", "草稿披露页"),
        ):
            path = root / receipt[path_key]
            if not path.is_file() or receipt.get(hash_key) != sha256_file(path):
                errors.append(f"{label}缺失或已变化")
        artifact = root / receipt["artifact_path"]
        try:
            _require_pdf(artifact)
        except ContractError as exc:
            errors.append(str(exc))
        if receipt.get("template_manifest_sha256") != sha256_file(root / MANIFEST_PATH):
            errors.append("草稿编译回执未绑定当前模板清单")
    except (ContractError, KeyError, OSError, ValueError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}


def compile_docx(
    paper_dir: Path,
    *,
    engine: str,
    timeout_seconds: int = 120,
    reference_docx: Path | None = None,
) -> Path:
    """用 pandoc 从论文源文件生成 Word 格式（.docx）。

    部分竞赛的交付配置要求同时提交 Word 版本；本函数在 PDF 编译完成后由
    ``compile_paper`` 尝试调用，也可单独调用以重新生成 .docx 而不重新编译 PDF。
    pandoc 缺失时由调用方决定是否降级（见 ``compile_paper`` 的 ``docx_skipped_reason``）。

    Args:
        paper_dir: 论文源文件目录（即 ``run_dir/paper/``）。
        engine: 当前编译引擎，``"latex"`` 或 ``"typst"``。
        timeout_seconds: pandoc 最长允许秒数。
        reference_docx: 可选的 Word 样式参考模板；只提供样式和外层排版。

    Returns:
        生成的 ``paper_dir/final.docx`` 路径。

    Raises:
        ContractError: pandoc 未安装、转换失败或产物为空。
    """
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise ContractError(
            "论文编译要求同时生成 Word（.docx）版本，但当前环境未检测到 pandoc。"
            "请安装 pandoc（https://pandoc.org/installing.html）后重试。"
        )
    entrypoint = paper_dir / ("main.tex" if engine == "latex" else "main.typ")
    if not entrypoint.is_file():
        raise ContractError(f"pandoc 转换需要源文件 {entrypoint.name}，但文件不存在")
    out = paper_dir / "final.docx"
    command = [pandoc, str(entrypoint), "-o", str(out), "--quiet"]
    if reference_docx is not None:
        reference_docx = reference_docx.resolve()
        if (
            not reference_docx.is_file()
            or reference_docx.suffix.casefold() != ".docx"
            or reference_docx.stat().st_size == 0
        ):
            raise ContractError(f"Pandoc 参考 Word 模板无效: {reference_docx}")
        command.append(f"--reference-doc={reference_docx}")
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
        raise ContractError(f"pandoc 转换超时（{timeout_seconds} 秒）") from exc
    except OSError as exc:
        raise ContractError(f"无法启动 pandoc: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip().replace("\n", " ")[:600]
        raise ContractError(f"pandoc 转换失败（退出码 {completed.returncode}）: {message}")
    if not out.is_file() or out.stat().st_size == 0:
        raise ContractError("pandoc 执行成功但未产生非空 final.docx")
    return out


def _external_compile_source(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    """外部交接已接受时，返回外部稿的编译目录与入口。

    返回 ``{"compile_dir", "entrypoint"}``；内部写作模式或外部稿尚未物化时
    返回 ``None``，compile_paper 继续使用模板入口。
    """
    from shumozizi.simple.authoring import read_authoring

    authoring = read_authoring(root)
    if authoring["authoring_mode"] != "external_handoff":
        return None
    if authoring["authoring_status"] not in {"draft_imported", "author_pass_accepted"}:
        return None
    entry = root / "paper/imported-author/main.tex"
    if not entry.is_file():
        return None
    return {"compile_dir": root / "paper/imported-author", "entrypoint": entry}


def _require_external_source_fresh(root: Path) -> None:
    """编译外部稿前，确认物化版本仍匹配当前外部稿与当前交接材料。

    外部稿被修改或上游正式结果/素材变化后，旧物化版本必须 stale 并阻断编译；
    草稿永远保留，只标记 needs_rebase 并提示重新 materialize/导入。
    """
    from shumozizi.paper.handoff import verify_handoff_freshness
    from shumozizi.paper.import_audit import IMPORTED_AUTHOR_RECEIPT
    from shumozizi.simple.authoring import mark_authoring_status, read_authoring

    freshness = verify_handoff_freshness(root)
    if not freshness["fresh"]:
        status = read_authoring(root)["authoring_status"]
        if status in {"draft_imported", "author_pass_accepted"}:
            mark_authoring_status(root, "needs_rebase")
        raise ContractError(
            "Writer Handoff 已 stale（" + "; ".join(freshness["reasons"][:3]) + "）；"
            "外部稿保留，请重建交接包并重新导入"
        )
    draft = root / "paper/external-author/draft.tex"
    receipt_path = root / IMPORTED_AUTHOR_RECEIPT
    if not receipt_path.is_file():
        raise ContractError(
            "缺少物化回执 paper/imported-author/receipt.json，请重新 materialize_external_draft"
        )
    receipt = load_json(receipt_path)
    if not draft.is_file() or sha256_file(draft) != receipt.get("external_draft_sha256"):
        raise ContractError("外部稿已变化，物化版本已 stale；请重新 materialize_external_draft")


def compile_paper(
    run_dir: Path,
    *,
    timeout_seconds: int = 300,
    revision_impact: str = "auto",
    reference_docx: Path | None = None,
    strict_editorial: bool = False,
    enforce_page_budget: bool = False,
) -> dict[str, Any]:
    """按模板清单编译论文，优先执行已选择的 LaTeX 引擎。

    Args:
        run_dir: 当前 v3 运行目录。
        timeout_seconds: 单次编译命令允许的最长秒数。
        reference_docx: 可选的 CUMCM Word 样式参考模板。
        strict_editorial: 是否要求当前长篇首稿已有独立冷读记录。
        enforce_page_budget: 已弃用的兼容参数；页数只生成编辑信号。

    Returns:
        已写入 ``paper/compile-receipt.json`` 的冻结编译收据。

    Raises:
        ContractError: 模板、编译器、输入或输出不满足受控编译边界。
    """
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("论文编译 timeout_seconds 必须在 1 至 3600 之间")
    from shumozizi.simple.authoring import require_internal_authoring

    require_internal_authoring(run_dir)
    if revision_impact not in {"auto", "render", "argument", "science"}:
        raise ContractError("revision_impact 必须为 auto、render、argument 或 science")
    root = run_dir.resolve()
    strict_mode = bool(strict_editorial or (root / LONGFORM_DRAFT_RECEIPT_PATH).is_file())
    # ── 编译前最小编译前提硬门：科学放行 + （内部）论证/编辑闭环 或 （外部）审计/裁决闭环 ──
    from shumozizi.simple.review import require_paper_generation_allowed

    require_paper_generation_allowed(run_dir)
    state = read_simple_state(run_dir)
    external_source = _external_compile_source(root, state)
    if external_source is not None:
        from shumozizi.paper.adjudication import require_paper_editorial_adjudication
        from shumozizi.paper.import_audit import require_import_audit_passed

        require_paper_editorial_adjudication(root)
        require_import_audit_passed(root)
        _require_external_source_fresh(root)
    else:
        from shumozizi.paper.editorial import require_editorial_readiness
        from shumozizi.paper.readiness import require_paper_readiness

        require_paper_readiness(run_dir)
        require_editorial_readiness(run_dir, require_record=strict_mode)
    previous_render_revision = int(state.get("paper_render_revision", 0))
    previous_argument_revision = int(state.get("argument_revision", previous_render_revision))
    manifest = require_materialized_template(run_dir)
    paper_dir = root / "paper"
    if external_source is not None:
        # 外部交接已接受：编译入口是审计通过的 imported-author/main.tex。
        compile_dir = external_source["compile_dir"]
        entrypoint = external_source["entrypoint"]
    else:
        compile_dir = paper_dir
        entrypoint = paper_dir / manifest["question_layout"]["entrypoint_path"]
    if not entrypoint.is_file():
        raise ContractError("论文编译入口缺失，不能编译")
    source_sha256 = _paper_source_sha256(compile_dir)
    resolved_impact = revision_impact
    if revision_impact == "auto":
        previous_receipt_path = root / COMPILE_RECEIPT_PATH
        previous_source_sha256: str | None = None
        if previous_receipt_path.is_file():
            try:
                previous_source_sha256 = load_json(previous_receipt_path).get("paper_source_sha256")
            except (OSError, ValueError):
                previous_source_sha256 = None
        resolved_impact = (
            "argument"
            if previous_argument_revision == 0 or previous_source_sha256 != source_sha256
            else "render"
        )
    argument_changed = resolved_impact in {"argument", "science"}
    next_argument_revision = previous_argument_revision + int(
        argument_changed or previous_argument_revision == 0
    )
    compiler, steps = _compiler_steps(manifest["engine"])
    executions = _run_compiler_steps(compile_dir, steps, timeout_seconds=timeout_seconds)

    compiled_pdf = compile_dir / ("final.pdf" if manifest["engine"] == "typst" else "main.pdf")
    _require_pdf(compiled_pdf)
    final_pdf = paper_dir / "final.pdf"
    if compiled_pdf != final_pdf:
        shutil.copy2(compiled_pdf, final_pdf)
    _require_pdf(final_pdf)
    if _paper_source_sha256(compile_dir) != source_sha256:
        raise ContractError("论文源文件在编译期间发生变化，拒绝冻结不稳定产物")

    page_budget: dict[str, Any] | None = None
    if strict_mode:
        from shumozizi.paper.page_budget import audit_page_budget

        page_budget = audit_page_budget(root, final_pdf, enforce_minimum=False)

    # PDF 已冻结，尝试生成同步交付的 Word 版本。
    # pandoc 缺失时不阻断 PDF 交付——记录跳过原因供后续补生成，而非让整个
    # 编译失败。竞赛要求同时提交 .docx 的场合，补生成后需重新运行本函数或
    # 单独调用 compile_docx。
    docx_skipped_reason: str | None = None
    final_docx: Path | None = None
    docx_qa: dict[str, Any] | None = None
    selected_reference_docx: Path | None = None
    if external_source is None:
        from shumozizi.paper.cumcm_adapter import (
            require_cumcm_structure_map,
            resolve_cumcm_reference_docx,
        )

        structure_map = require_cumcm_structure_map(root)
        selected_reference_docx = reference_docx.resolve() if reference_docx is not None else None
        if selected_reference_docx is None and structure_map is not None:
            selected_reference_docx = resolve_cumcm_reference_docx(root, structure_map)
        if selected_reference_docx is not None and (
            not selected_reference_docx.is_file()
            or selected_reference_docx.suffix.casefold() != ".docx"
            or selected_reference_docx.stat().st_size == 0
        ):
            raise ContractError(f"Word 参考模板无效: {selected_reference_docx}")
        try:
            compile_kwargs: dict[str, Any] = {
                "engine": manifest["engine"],
                "timeout_seconds": timeout_seconds,
            }
            if selected_reference_docx is not None:
                compile_kwargs["reference_docx"] = selected_reference_docx
            final_docx = compile_docx(paper_dir, **compile_kwargs)
            docx_qa = audit_docx(root, final_docx, timeout_seconds=timeout_seconds)
            if not docx_qa["success"]:
                raise ContractError("DOCX 内容 QA 失败: " + "; ".join(docx_qa["errors"]))
            # Word 页数同 PDF 页数：只作为编辑信号记录在 docx_qa 中，不硬阻断。
        except ContractError as exc:
            # 仅在 pandoc 缺失时降级，其他 ContractError（转换失败、产物为空）仍阻断。
            if "未检测到 pandoc" in str(exc):
                docx_skipped_reason = str(exc)
            else:
                raise
    else:
        # 外部稿正文与内部模板无关：Word 由外部稿单独生成，本路径只交付 PDF。
        docx_skipped_reason = "external_author_compile: Word 由外部稿单独生成"

    manifest_path = root / MANIFEST_PATH
    receipt: dict[str, Any] = {
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
        "strict_mode": strict_mode,
        "generated_at": utc_now(),
    }
    from shumozizi.paper.policy import formal_result_digest, policy_fingerprint

    receipt["formal_result_digest"] = formal_result_digest(root)
    repo_root = resolve_repo_root(Path(__file__))
    receipt["paper_policy_fingerprint"] = policy_fingerprint(repo_root, "paper")
    receipt["visual_policy_fingerprint"] = policy_fingerprint(repo_root, "visual")
    if external_source is not None:
        from shumozizi.paper.import_audit import IMPORTED_AUTHOR_RECEIPT

        imported = load_json(root / IMPORTED_AUTHOR_RECEIPT)
        receipt["external_author_compile"] = True
        receipt["external_draft_sha256"] = imported["external_draft_sha256"]
        receipt["import_audit_sha256"] = imported["import_audit_sha256"]
        receipt["handoff_revision"] = imported["handoff_revision"]
    if selected_reference_docx is not None:
        receipt["reference_docx_path"] = str(selected_reference_docx)
        receipt["reference_docx_sha256"] = sha256_file(selected_reference_docx)
    if page_budget is not None:
        from shumozizi.paper.page_budget import PAGE_BUDGET_PATH

        receipt["page_budget_path"] = PAGE_BUDGET_PATH.as_posix()
        receipt["page_budget_sha256"] = sha256_file(root / PAGE_BUDGET_PATH)
        receipt["page_count"] = page_budget["page_count"]
        receipt["page_budget_status"] = page_budget["status"]
    if state.get("schema_version") == "3.2":
        receipt["paper_render_revision"] = previous_render_revision + 1
        receipt["render_revision"] = previous_render_revision + 1
        receipt["argument_revision"] = next_argument_revision
        receipt["revision_impact"] = resolved_impact
    if final_docx is not None:
        receipt["final_docx_path"] = "paper/final.docx"
        receipt["final_docx_sha256"] = sha256_file(final_docx)
        receipt["docx_qa_path"] = "qa/docx-structure.json"
        receipt["docx_qa_sha256"] = sha256_file(root / "qa" / "docx-structure.json")
    if docx_skipped_reason is not None:
        receipt["docx_skipped_reason"] = docx_skipped_reason
    _require_schema(receipt)
    atomic_json(root / COMPILE_RECEIPT_PATH, receipt)
    if state.get("schema_version") == "3.2":
        from shumozizi.simple.state import record_paper_compilation

        record_paper_compilation(
            root,
            previous_render_revision=previous_render_revision,
            argument_changed=argument_changed,
        )
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
        receipt_revision = receipt.get("paper_render_revision")
        if receipt_revision is not None and receipt_revision != state.get(
            "paper_render_revision", 0
        ):
            errors.append("编译回执未绑定当前论文渲染修订")
        if receipt.get("render_revision") is not None and receipt.get(
            "render_revision"
        ) != state.get("render_revision", state.get("paper_render_revision", 0)):
            errors.append("编译回执未绑定当前 render_revision")
        if receipt.get("argument_revision") is not None and receipt.get(
            "argument_revision"
        ) != state.get("argument_revision", 0):
            errors.append("编译回执未绑定当前 argument_revision")
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
        # 外部 Author 编译时，入口与源码都在 paper/imported-author/ 下。
        external_compile = receipt.get("external_author_compile") is True
        if external_compile:
            expected_entry = root / "paper/imported-author/main.tex"
            source_dir = root / "paper/imported-author"
        else:
            expected_entry = root / "paper" / manifest["question_layout"]["entrypoint_path"]
            source_dir = root / "paper"
        if entrypoint.resolve() != expected_entry.resolve() or not entrypoint.is_file():
            errors.append("编译回执入口与当前编译源不一致")
        elif receipt["entrypoint_sha256"] != sha256_file(entrypoint):
            errors.append("论文入口在编译后已变化")
        if receipt["paper_source_sha256"] != _paper_source_sha256(source_dir):
            errors.append("论文源文件在编译后已变化")
        from shumozizi.paper.policy import formal_result_digest, policy_fingerprint

        expected_result_digest = formal_result_digest(root)
        if receipt.get("formal_result_digest") not in {None, expected_result_digest}:
            errors.append("编译回执未绑定当前正式生产结果")
        if receipt.get("paper_policy_fingerprint") not in {
            None,
            policy_fingerprint(resolve_repo_root(Path(__file__)), "paper"),
        }:
            errors.append("编译回执未绑定当前论文政策")
        if receipt.get("visual_policy_fingerprint") not in {
            None,
            policy_fingerprint(resolve_repo_root(Path(__file__)), "visual"),
        }:
            errors.append("编译回执未绑定当前视觉政策")
        final_pdf = root / receipt["final_pdf_path"]
        try:
            _require_pdf(final_pdf)
            if receipt["final_pdf_sha256"] != sha256_file(final_pdf):
                errors.append("最终 PDF 在编译后已变化")
        except ContractError as exc:
            errors.append(str(exc))
        if "page_budget_path" in receipt:
            from shumozizi.paper.page_budget import verify_page_budget

            page_budget = verify_page_budget(root, pdf_path=final_pdf)
            if not page_budget["valid"]:
                errors.extend(page_budget["errors"])
            report_path = root / receipt["page_budget_path"]
            if not report_path.is_file() or receipt.get("page_budget_sha256") != sha256_file(
                report_path
            ):
                errors.append("编译回执未绑定当前页数审计")
            elif receipt.get("page_count") != page_budget["report"].get("page_count"):
                errors.append("编译回执 page_count 与页数审计不一致")
        if "reference_docx_path" in receipt:
            reference = Path(receipt["reference_docx_path"])
            if not reference.is_file() or receipt.get("reference_docx_sha256") != sha256_file(
                reference
            ):
                errors.append("编译回执绑定的 Word 参考模板已缺失或变化")
        # DOCX 字段是可选的（pandoc 缺失时跳过）；有则复验，跳过则忽略。
        if "final_docx_path" in receipt:
            final_docx = root / receipt["final_docx_path"]
            if not final_docx.is_file() or final_docx.stat().st_size == 0:
                errors.append("回执记录了 final.docx 但文件不存在或为空")
            elif receipt.get("final_docx_sha256") != sha256_file(final_docx):
                errors.append("最终 .docx 在编译后已变化")
            docx_qa = root / receipt.get("docx_qa_path", "")
            if not docx_qa.is_file():
                errors.append("DOCX QA 报告不存在")
            elif receipt.get("docx_qa_sha256") != sha256_file(docx_qa):
                errors.append("DOCX QA 报告在编译后已变化")
    except (ContractError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}
