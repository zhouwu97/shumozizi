"""选择、实例化并复验 v3 竞赛论文模板。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_tree
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.state import read_simple_state, utc_now

MANIFEST_PATH = Path("paper/template_manifest.json")
_COMPETITION_ALIASES = {
    "全国大学生数学建模竞赛": "cumcm",
    "全国大学生数学建模": "cumcm",
    "cumcm": "cumcm",
    "national": "cumcm",
    "国赛": "cumcm",
    "美国大学生数学建模竞赛": "mcm",
    "美国大学生数学建模": "mcm",
    "comap": "mcm",
    "icm": "mcm",
    "mcm": "mcm",
    "亚太地区大学生数学建模竞赛": "apmcm",
    "亚太数学建模竞赛": "apmcm",
    "apmcm": "apmcm",
    "长三角高校数学建模竞赛": "changsanjiao",
    "长三角": "changsanjiao",
    "changsanjiao": "changsanjiao",
    "电工杯": "diangongbei",
    "diangongbei": "diangongbei",
    "东北三省数学建模联赛": "dongsansheng",
    "东三省": "dongsansheng",
    "dongsansheng": "dongsansheng",
    "华数杯": "huashubei",
    "huashubei": "huashubei",
    "华为杯": "huaweibei",
    "huaweibei": "huaweibei",
    "华中杯": "huazhongbei",
    "huazhongbei": "huazhongbei",
    "mathorcup": "mathorcup",
    "数维杯": "shuweibei",
    "shuweibei": "shuweibei",
    "统计建模大赛": "stats",
    "统计建模": "stats",
    "stats": "stats",
    "五一杯": "wuyibei",
    "wuyibei": "wuyibei",
}
_SECTION_PATH_REFERENCE = re.compile(r"sections/(?P<path>[^\"'{}()\s]+)", re.IGNORECASE)
_TYPST_BODY_INCLUDE = re.compile(
    r"^\s*#include\s*(?:\(\s*)?[\"'](?P<path>sections/[^\"'\s)]+)[\"']\s*\)?\s*$"
)
_LATEX_BODY_INCLUDE = re.compile(
    r"^\s*\\(?:input|include)\s*\{\s*(?P<path>sections/[^}\s]+)\s*\}"
)
_NON_BODY_SECTION_STEMS = {"a_code", "appendices1", "abstract"}
_LATEX_COMMANDS = ("latexmk", "xelatex", "pdflatex", "tectonic")


def _schema() -> dict[str, Any]:
    """读取论文模板选择清单 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "paper_template_manifest.schema.json")


def _require_schema(payload: dict[str, Any]) -> None:
    """校验模板选择清单的结构。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))


def _template_base(competition: str, language: str) -> str:
    """将已识别竞赛映射为仓内完整写作 Skill 的模板键。"""
    normalized = competition.strip().casefold()
    root = resolve_repo_root(Path(__file__)) / "skills" / "5writing" / "templates" / language
    for marker, base in sorted(_COMPETITION_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if marker in normalized:
            if (root / base).is_dir():
                return base
            raise ContractError(f"竞赛 {competition} 没有可用的 {language} 模板")
    if normalized != "default" and (root / normalized).is_dir():
        return normalized
    raise ContractError("未识别比赛类型，不能静默回退 default；请指定已有模板键或补充映射")


def _source_dir(language: str, base: str, engine: str) -> tuple[str, Path]:
    """解析模板 ID 与必须存在的入口文件。"""
    suffix = "" if engine == "typst" else "-latex"
    template_id = f"{language}/{base}{suffix}"
    root = resolve_repo_root(Path(__file__))
    source = root / "skills" / "5writing" / "templates" / language / f"{base}{suffix}"
    entrypoint = source / ("main.typ" if engine == "typst" else "main.tex")
    if not entrypoint.is_file():
        raise ContractError(f"完整写作 Skill 缺少匹配模板入口: {template_id}")
    return template_id, source


def _entry_name(engine: str) -> str:
    """返回给定排版引擎的模板入口名称。"""
    return "main.typ" if engine == "typst" else "main.tex"


def _question_section_path(engine: str) -> str:
    """返回动态问题章节相对于 paper/ 的稳定路径。"""
    return f"sections/questions.{ 'typ' if engine == 'typst' else 'tex'}"


def _is_dynamic_question_reference(reference: str, section_path: str, engine: str) -> bool:
    """判断入口引用是否正好指向当前动态问题章节。

    LaTeX 的 ``\\input`` 可省略 ``.tex`` 后缀，Typst 则必须保留 ``.typ``。
    因此不能直接比较字符串，否则会把已替换的动态章节重新判成旧示例正文。
    """
    normalized_reference = Path(reference).as_posix().casefold()
    normalized_section = Path(section_path).as_posix().casefold()
    if engine == "latex":
        normalized_reference = str(Path(normalized_reference).with_suffix(""))
        normalized_section = str(Path(normalized_section).with_suffix(""))
    return normalized_reference == normalized_section


def _section_stem(reference: str) -> str:
    """返回模板章节引用的无扩展名小写名称。"""
    return Path(reference).stem.casefold()


def _is_non_body_section(reference: str) -> bool:
    """判断章节是否为附录或摘要等非正文入口。"""
    return _section_stem(reference) in _NON_BODY_SECTION_STEMS


def _body_section_reference(line: str, engine: str) -> str | None:
    """只识别可被动态问题入口替换的正文 include。

    Typst 的 import 和 let include 可能提供模板函数或附录入口，不能与正文
    include 混为一谈。误删这些依赖会让模板表面上被实例化、实际却无法编译或
    残留样例符号。
    """
    pattern = _TYPST_BODY_INCLUDE if engine == "typst" else _LATEX_BODY_INCLUDE
    matched = pattern.match(line)
    return matched.group("path") if matched else None


def _body_section_references(source: Path, engine: str) -> list[str]:
    """收集模板入口中可安全接管的静态正文 section 引用。"""
    content = (source / _entry_name(engine)).read_text(encoding="utf-8")
    return [
        reference
        for line in content.splitlines()
        if (reference := _body_section_reference(line, engine)) is not None
        and not _is_non_body_section(reference)
    ]


def _unsupported_body_dependencies(source: Path, engine: str) -> list[str]:
    """找出正文 include 之外仍依赖的正文 section。

    这类依赖通常是 Typst 模板把示例正文定义为 import。自动删除示例正文会破坏
    入口，保留它又会把示例内容带入论文，因此必须由模板维护者先增加明确锚点。
    """
    content = (source / _entry_name(engine)).read_text(encoding="utf-8")
    body_includes = set(_body_section_references(source, engine))
    return sorted(
        {
            f"sections/{match.group('path')}"
            for match in _SECTION_PATH_REFERENCE.finditer(content)
            if not _is_non_body_section(match.group("path"))
            and f"sections/{match.group('path')}" not in body_includes
        }
    )


def _has_question_insertion_anchor(source: Path, engine: str) -> bool:
    """判断模板能否由动态章节适配器安全接管问题正文。

    只有原模板已经把正文拆入 ``sections/`` 才能做机械改写。把整段内联示例
    猜测为可替换正文会留下隐性示例结论，因此宁可显式阻断等待模板维护。
    """
    return bool(_body_section_references(source, engine)) and not _unsupported_body_dependencies(
        source, engine
    )


def _require_dynamic_question_support(language: str, base: str, engine: str) -> None:
    """确认所选引擎可安全插入当前题目章节。

    Typst 与 LaTeX 的模板维护是相互独立的。选择 LaTeX 不应因未选用的 Typst
    模板缺少锚点而被阻断；全矩阵覆盖由模板回归测试单独报告。
    """
    template_id, source = _source_dir(language, base, engine)
    if not _has_question_insertion_anchor(source, engine):
        dependencies = _unsupported_body_dependencies(source, engine)
        suffix = (
            "；正文依赖未受控 section: " + ", ".join(dependencies)
            if dependencies
            else ""
        )
        raise ContractError(f"模板 {template_id} 缺少安全的动态问题章节插入点{suffix}")


def _question_section_content(language: str, engine: str, question_ids: list[str]) -> str:
    """生成不携带旧示例文本的动态问题入口。"""
    title = "问题" if language == "zh" else "Problem"
    if engine == "typst":
        lines = [f"= {title} {question_id}\n" for question_id in question_ids]
    else:
        lines = [f"\\section{{{title} {question_id}}}\n" for question_id in question_ids]
    return "\n".join(lines)


def _question_include_line(engine: str) -> str:
    """生成动态问题章节的唯一入口行。"""
    return '#include("sections/questions.typ")' if engine == "typst" else "\\input{sections/questions}"


def _dynamic_outline_lines(language: str, engine: str) -> list[str]:
    """生成与动态问题章节一致的目录入口。"""
    title = "目录" if language == "zh" else "Contents"
    if engine == "typst":
        return [f"#outline(title: [{title}], depth: 3)", "#pagebreak()"]
    return ["\\tableofcontents", "\\newpage"]


def _replace_static_outline(lines: list[str], language: str, engine: str) -> list[str]:
    """移除手写 Problem 1--3 目录，避免赛事格式正确而题目结构错误。"""
    if engine == "typst":
        rewritten: list[str] = []
        for line in lines:
            if line.strip() in {"#toc-page()", "#contents-page()"}:
                rewritten.extend(_dynamic_outline_lines(language, engine))
            else:
                rewritten.append(line)
        return rewritten

    rewritten = []
    inserted = False
    for line in lines:
        if line.lstrip().startswith("\\tocentry{"):
            if not inserted:
                rewritten.extend(_dynamic_outline_lines(language, engine))
                inserted = True
            continue
        rewritten.append(line)
    return rewritten


def _replace_question_includes(entry: Path, engine: str, language: str) -> None:
    """用动态问题章节替换全部静态正文入口。"""
    lines = entry.read_text(encoding="utf-8").splitlines()
    include_line = _question_include_line(engine)
    rewritten: list[str] = []
    replaced = False
    for line in lines:
        reference = _body_section_reference(line, engine)
        if reference is not None and not _is_non_body_section(reference):
            if not replaced:
                rewritten.append(include_line)
                replaced = True
            continue
        rewritten.append(line)
    if not replaced:
        raise ContractError("模板入口缺少可安全替换的静态正文章节")
    rewritten = _replace_static_outline(rewritten, language, engine)
    entry.write_text("\n".join(rewritten) + "\n", encoding="utf-8", newline="\n")


def _clear_static_section_content(paper_dir: Path, engine: str) -> None:
    """删除不会再被入口引用的示例正文，并清空保留的附录/摘要样例。"""
    sections = paper_dir / "sections"
    suffix = ".typ" if engine == "typst" else ".tex"
    for section in sections.glob(f"*{suffix}"):
        stem = section.stem.casefold()
        if stem == "questions":
            continue
        if stem in _NON_BODY_SECTION_STEMS:
            marker = "// 正式论文内容由写作阶段填写。\n" if engine == "typst" else "% 正式论文内容由写作阶段填写。\n"
            section.write_text(marker, encoding="utf-8", newline="\n")
        else:
            section.unlink()


def _clear_template_references(paper_dir: Path, engine: str) -> None:
    """清空模板示例参考文献，避免样例作者或引文进入正式论文。

    模板可以保留引用入口和排版样式，但参考文献内容必须由当前运行的作者
    根据实际采用的方法填写。空注释对 LaTeX 和 Typst 都是合法输入，因此不会
    通过保留示例条目来换取可编译性。
    """
    filename = "references.typ" if engine == "typst" else "references.tex"
    target = paper_dir / filename
    if not target.is_file():
        return
    marker = (
        "// 正式参考文献由写作阶段按实际使用的方法填写。\n"
        if engine == "typst"
        else "% 正式参考文献由写作阶段按实际使用的方法填写。\n"
    )
    target.write_text(marker, encoding="utf-8", newline="\n")


def _install_question_layout(run_dir: Path, manifest: dict[str, Any]) -> None:
    """按当前题目数实例化问题章节，并去除源模板的旧示例章节。"""
    layout = manifest["question_layout"]
    question_ids = layout["question_ids"]
    if not question_ids:
        raise ContractError("未声明必答问题，不能实例化动态论文模板")
    paper_dir = run_dir / "paper"
    entry = paper_dir / layout["entrypoint_path"]
    section = paper_dir / layout["section_path"]
    if section.exists():
        raise ContractError("动态问题章节已存在，拒绝覆盖")
    _replace_question_includes(entry, manifest["engine"], manifest["language"])
    section.write_text(
        _question_section_content(manifest["language"], manifest["engine"], question_ids),
        encoding="utf-8",
        newline="\n",
    )
    _clear_static_section_content(paper_dir, manifest["engine"])
    _clear_template_references(paper_dir, manifest["engine"])


def _require_question_layout(run_dir: Path, manifest: dict[str, Any]) -> None:
    """确认实例化模板仍保留当前题目数对应的唯一章节入口。"""
    if manifest["schema_version"] not in {"1.1", "1.2"}:
        return
    layout = manifest["question_layout"]
    if not layout["question_ids"]:
        raise ContractError("模板清单没有必答问题，不能证明论文结构完整")
    paper_dir = run_dir / "paper"
    entry = paper_dir / layout["entrypoint_path"]
    section = paper_dir / layout["section_path"]
    if not section.is_file() or section.stat().st_size == 0:
        raise ContractError("模板缺少当前题目数对应的动态问题章节")
    entry_text = entry.read_text(encoding="utf-8")
    include_line = _question_include_line(manifest["engine"])
    if entry_text.count(include_line) != 1:
        raise ContractError("模板入口必须且只能包含一次动态问题章节")
    stale_references = [
        reference
        for line in entry_text.splitlines()
        if (reference := _body_section_reference(line, manifest["engine"])) is not None
        and not _is_non_body_section(reference)
        and not _is_dynamic_question_reference(
            reference,
            layout["section_path"],
            manifest["engine"],
        )
    ]
    if stale_references:
        raise ContractError("模板入口仍引用旧的固定正文章节: " + ", ".join(stale_references))
    content = section.read_text(encoding="utf-8")
    title = "问题" if manifest["language"] == "zh" else "Problem"
    missing = [question_id for question_id in layout["question_ids"] if f"{title} {question_id}" not in content]
    if missing:
        raise ContractError("动态问题章节与题目数量不一致: " + ", ".join(missing))


def _available_paper_engines() -> tuple[dict[str, str], str | None]:
    """探测可用排版引擎，供自动选择留下可审计的受控依据。"""
    latex = {name: command for name in _LATEX_COMMANDS if (command := shutil.which(name))}
    return latex, shutil.which("typst")


def _resolve_paper_engine(engine: str | None) -> tuple[str, str, bool, str | None]:
    """解析用户意图，默认优先 LaTeX，禁止静默切换排版引擎。"""
    requested = "auto" if engine is None else engine.strip().casefold()
    if requested not in {"auto", "latex", "typst"}:
        raise ContractError("论文排版引擎必须为 auto、latex 或 typst")
    latex, typst = _available_paper_engines()
    if requested == "latex":
        if not latex:
            raise ContractError("已显式选择 LaTeX，但未检测到 latexmk/xelatex/pdflatex/tectonic")
        return "latex", requested, False, None
    if requested == "typst":
        if not typst:
            raise ContractError("已显式选择 Typst，但未检测到 typst")
        return "typst", requested, False, None
    if latex:
        return "latex", requested, False, None
    if typst:
        return (
            "typst",
            requested,
            True,
            "未检测到 latexmk/xelatex/pdflatex/tectonic；已受控回退到 Typst。",
        )
    raise ContractError("未检测到可用 LaTeX 或 Typst 排版引擎，不能选择论文模板")


def select_paper_template(
    run_dir: Path,
    *,
    language: str,
    engine: str | None = "auto",
    selection_reason: str,
) -> dict[str, Any]:
    """选择一个与比赛、语言和引擎匹配的完整模板，不复制文件。

    Args:
        run_dir: v3 运行目录。
        language: ``zh`` 或 ``en``。
        engine: ``auto``（默认优先 LaTeX）、``latex`` 或 ``typst``。
        selection_reason: 对比赛与模板匹配的可审计理由。

    Returns:
        已保存的模板选择清单。
    """
    state = read_simple_state(run_dir)
    if language not in {"zh", "en"}:
        raise ContractError("论文语言必须为 zh/en")
    if not state["competition"].strip():
        raise ContractError("未声明 competition，不能选择论文模板")
    if not state["required_questions"]:
        raise ContractError("未声明 required_questions，不能选择论文模板")
    actual_engine, requested_engine, fallback_used, fallback_reason = _resolve_paper_engine(engine)
    base = _template_base(state["competition"], language)
    template_id, source = _source_dir(language, base, actual_engine)
    _require_dynamic_question_support(language, base, actual_engine)
    root = resolve_repo_root(Path(__file__))
    payload = {
        "schema_version": "1.2",
        "run_id": state["run_id"],
        "competition": state["competition"],
        "language": language,
        "engine": actual_engine,
        "requested_engine": requested_engine,
        "template_id": template_id,
        "source_path": source.relative_to(root).as_posix(),
        "source_sha256": sha256_tree(source),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "selection_reason": selection_reason,
        "question_layout": {
            "question_ids": list(state["required_questions"]),
            "section_path": _question_section_path(actual_engine),
            "entrypoint_path": _entry_name(actual_engine),
        },
        "created_at": utc_now(),
    }
    _require_schema(payload)
    atomic_json(run_dir / MANIFEST_PATH, payload)
    return payload


def materialize_selected_template(run_dir: Path) -> dict[str, Any]:
    """将选择的完整模板复制到空白论文入口，拒绝覆盖已有正文。

    ``paper/sections`` 是运行目录骨架，不视为正文模板冲突；其他同名模板文件
    已存在时必须由写作任务显式处理，避免覆盖用户的论文内容。
    """
    manifest = read_template_manifest(run_dir)
    root = resolve_repo_root(Path(__file__))
    source = root / manifest["source_path"]
    paper_dir = run_dir / "paper"
    entry_name = _entry_name(manifest["engine"])
    if (paper_dir / entry_name).exists():
        raise ContractError(f"论文入口已存在，拒绝覆盖: paper/{entry_name}")
    for item in source.iterdir():
        target = paper_dir / item.name
        if target.exists() and item.name != "sections":
            raise ContractError(f"模板目标已存在，拒绝覆盖: paper/{item.name}")
    for item in source.iterdir():
        target = paper_dir / item.name
        if item.is_dir():
            if item.name == "sections":
                target.mkdir(parents=True, exist_ok=True)
                for child in item.iterdir():
                    child_target = target / child.name
                    if child_target.exists():
                        raise ContractError(f"模板章节已存在，拒绝覆盖: {child_target.name}")
                    shutil.copytree(child, child_target) if child.is_dir() else shutil.copy2(child, child_target)
            else:
                shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    _install_question_layout(run_dir, manifest)
    return read_template_manifest(run_dir)


def read_template_manifest(run_dir: Path) -> dict[str, Any]:
    """读取并验证模板来源未变化的清单。"""
    manifest_path = run_dir / MANIFEST_PATH
    if not manifest_path.is_file():
        raise ContractError("缺少论文模板清单 paper/template_manifest.json")
    payload = load_json(manifest_path)
    _require_schema(payload)
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"] or payload["competition"] != state["competition"]:
        raise ContractError("论文模板清单与当前运行不一致")
    root = resolve_repo_root(Path(__file__))
    source = root / payload["source_path"]
    if not source.is_dir() or sha256_tree(source) != payload["source_sha256"]:
        raise ContractError("论文模板来源缺失或已漂移")
    expected_id, expected_source = _source_dir(
        payload["language"], _template_base(state["competition"], payload["language"]), payload["engine"]
    )
    if payload["template_id"] != expected_id or source.resolve() != expected_source.resolve():
        raise ContractError("论文模板与比赛类型或排版引擎不匹配")
    if payload["schema_version"] in {"1.1", "1.2"}:
        _require_dynamic_question_support(
            payload["language"],
            _template_base(state["competition"], payload["language"]),
            payload["engine"],
        )
        if payload["question_layout"]["question_ids"] != state["required_questions"]:
            raise ContractError("模板问题章节与当前 required_questions 不一致")
    return payload


def require_materialized_template(run_dir: Path) -> dict[str, Any]:
    """确保完整写作模板已经选择、未漂移且存在当前引擎入口。"""
    manifest = read_template_manifest(run_dir)
    entry_name = _entry_name(manifest["engine"])
    entry = run_dir / "paper" / entry_name
    if not entry.is_file() or entry.stat().st_size == 0:
        raise ContractError("未实例化完整写作模板的论文入口")
    _require_question_layout(run_dir, manifest)
    return manifest
