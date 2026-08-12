"""对外部 Author 稿件执行导入审计。

审计分两层：

- 第一层（机械结构）：能否编译、章节/公式环境是否平衡、交叉引用是否有效、
  图与引用键是否存在。
- 第二层（Scientific Binding）：把草稿中的数字、强科学主张、图引用、引用键
  与冻结的 ``answer-and-claims.json``、FIGURE_CATALOG、CITATION_PACKET 对照，
  产出 ``wrong_number``、``unsupported_claim``、``unknown_figure``、
  ``unknown_citation`` 等客观问题。

``wrong_number`` 先标记为 ``scientific_fact_candidate``，再由
``classify_fact_candidates`` 用 machine binding（正文数字 vs 正式结果）确认或
驳回；只有确认的 ``confirmed_scientific_fact_failure`` 属于不可申诉类别。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.paper.external_author import DRAFT_PATH, EXTERNAL_DIR, read_external_draft
from shumozizi.paper.handoff import (
    ANSWER_AND_CLAIMS_JSON,
    HANDOFF_DIR,
    HANDOFF_MANIFEST_PATH,
    verify_handoff_freshness,
)
from shumozizi.simple.authoring import mark_authoring_status
from shumozizi.simple.state import utc_now

AUDIT_PATH = Path("review/import-audit.json")
CONFIRMED_FAILURE_PATH = Path("review/confirmed-scientific-fact-failures.json")
IMPORTED_AUTHOR_DIR = Path("paper/imported-author")
IMPORTED_AUTHOR_ENTRYPOINT = IMPORTED_AUTHOR_DIR / "main.tex"
IMPORTED_AUTHOR_RECEIPT = IMPORTED_AUTHOR_DIR / "receipt.json"

ANSWER_CONTEXT = re.compile(
    r"答案|直接回答|最少|至少|最多|至多|需要.{0,10}人|结果为|最优|最小值|最大值|总计|共|"
    r"\banswer\b|\bresult\b|\bpeople\b|\bpersons\b",
    re.IGNORECASE,
)
STRONG_TRIGGERS = (
    "全局最优",
    "最优解",
    "唯一",
    "显著",
    "鲁棒",
    "稳健",
    "稳定",
    "证明",
    "必然",
    "泛化",
    "保证",
)
ENVIRONMENT_PATTERN = re.compile(r"\\begin\{([^}]+)\}")
INCLUDEGRAPHICS_PATTERN = re.compile(r"\\includegraphics(?:\s*\[[^\]]*\])?\{([^}]+)\}")
LABEL_PATTERN = re.compile(r"\\label\{([^}]+)\}")
REF_PATTERN = re.compile(r"\\ref\{([^}]+)\}")
CITE_PATTERN = re.compile(r"\\cite\{([^}]+)\}")


def _question_for_sentence(text: str, sentence_start: int, question_ids: list[str]) -> str | None:
    """根据句号位置之前的最近问题标题，尽力归属某问。"""
    prefix = text[:sentence_start]
    best: tuple[int, str] | None = None
    for question_id in question_ids:
        pattern = re.compile(rf"\b{re.escape(question_id)}\b|第\s*[{question_id[-1]}]\s*问")
        for match in pattern.finditer(prefix):
            if best is None or match.end() > best[0]:
                best = (match.end(), question_id)
    return best[1] if best else None


def _answer_sentences(text: str) -> list[str]:
    """切分句子并保留含答案语境的句子。"""
    sentences = re.split(r"(?<=[。！？；!?;])\s*", text)
    return [
        sentence.strip()
        for sentence in sentences
        if ANSWER_CONTEXT.search(sentence) and sentence.strip()
    ]


def _copy_external_assets(root: Path, dest: Path) -> None:
    """把外部稿目录的全部素材复制到目标目录，保留相对路径语义。

    真实草稿常含 ``\\input``、``\\includegraphics``、子文件等相对路径依赖；
    只复制 ``draft.tex`` 会在换目录后断裂。这里连同 companion 一起复制，
    ``draft.tex`` 落盘为目标目录的 ``main.tex``，不复制编译产物。
    """
    source = root / EXTERNAL_DIR
    dest.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if not path.is_file() or path.name in {"draft.pdf"}:
            continue
        if "build" in path.parts:
            continue
        relative = path.relative_to(source)
        if relative.as_posix() == DRAFT_PATH.name:
            target = dest / "main.tex"
        else:
            target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def compile_external_draft(run_dir: Path, *, timeout_seconds: int = 300) -> dict[str, Any]:
    """在隔离目录编译外部草稿，产出 ``draft.pdf`` 与编译回执。

    草稿原文件 ``draft.tex`` 不会被修改；编译在 ``paper/external-author/build/``
    内进行，成功后把 PDF 复制为 ``paper/external-author/draft.pdf``。

    Args:
        run_dir: 当前运行目录。
        timeout_seconds: 单次编译器调用的超时上限。

    Returns:
        ``{"compiled": bool, "engine": str|None, "errors": [str]}``。
    """
    root = run_dir.resolve()
    draft = root / DRAFT_PATH
    if not draft.is_file():
        raise ContractError("缺少外部草稿 draft.tex")
    from shumozizi.paper.compiler import _compiler_steps, _extract_latex_errors

    build_dir = root / EXTERNAL_DIR / "build"
    _copy_external_assets(root, build_dir)
    try:
        engine, steps = _compiler_steps("latex")
    except ContractError as exc:
        return {"compiled": False, "engine": None, "errors": [str(exc)]}
    errors: list[str] = []
    compiled = False
    for command in steps:
        try:
            completed = subprocess.run(
                command,
                cwd=build_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{engine} 编译超时（>{timeout_seconds}s）")
            break
        if completed.returncode != 0:
            detail = _extract_latex_errors(build_dir)
            errors.append(detail or f"{engine} 退出码 {completed.returncode}")
            break
    pdf = build_dir / "main.pdf"
    if pdf.is_file():
        shutil.copyfile(pdf, root / EXTERNAL_DIR / "draft.pdf")
        compiled = True
    return {"compiled": compiled, "engine": engine, "errors": errors}


def _normalize_number(value: str) -> float | None:
    """把数字字符串规范化为数值；解析失败返回 None。"""
    try:
        return float(value)
    except ValueError:
        return None


def _same_number(left: float, right: float) -> bool:
    """数值意义上的相等：581、581.0、581.000 视为相同，12 与 120 不同。"""
    return left == right


def _expected_answer_numbers(question: dict[str, Any]) -> list[float]:
    """读取正文必现数字；旧交接包继续兼容 ``must_answer``。"""
    if "essential_numbers" in question:
        values = question.get("essential_numbers")
        if not isinstance(values, list):
            return []
        return [
            number
            for value in values
            if (number := _normalize_number(str(value))) is not None
        ]
    return [
        number
        for token in re.findall(r"\d+(?:\.\d+)?", str(question.get("must_answer", "")))
        if (number := _normalize_number(token)) is not None
    ]


def _numbers_without_question_ids(text: str, question_id: str) -> list[float]:
    """提取文本中的数字，但先剔除题号（Q1 的 1 不应成为候选答案）。"""
    cleaned = text.replace(question_id, "")
    return [
        value
        for token in re.findall(r"\d+(?:\.\d+)?", cleaned)
        if (value := _normalize_number(token)) is not None
    ]


def _question_sections(text: str, question_ids: list[str]) -> dict[str, str]:
    """按题号标题把草稿切成逐问正文段。

    每问取最后一个标题出现位置到下一个不同标题之间的文本；未找到标题的问题
    得到空段。只用于数字绑定，不判断论证质量。
    """
    positions: list[tuple[int, str]] = []
    for question_id in question_ids:
        number = question_id[-1] if question_id and question_id[-1].isdigit() else ""
        pattern = re.compile(rf"\b{re.escape(question_id)}\b|第\s*{number}\s*问|问题\s*{number}")
        for match in pattern.finditer(text):
            positions.append((match.start(), question_id))
    positions.sort()
    sections: dict[str, str] = {question_id: "" for question_id in question_ids}
    for index, (start, question_id) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        # 同一问出现多次时取最后一次（通常为正文主体），目录项不抢占。
        sections[question_id] = text[start:end]
    return sections


def extract_numbers(draft_text: str, answer_and_claims: dict[str, Any]) -> list[dict[str, Any]]:
    """逐问把草稿数字与正式答案绑定，产出缺失/写错两类 finding。

    核验只在本问的正文段内进行，避免"某问数字出现在全文别处"掩盖真正的错误；
    数字按数值规范化比较（581/581.0 相同，12/120 不同）。
    """
    question_ids = [
        str(item.get("question_id", "")) for item in answer_and_claims.get("questions", [])
    ]
    sections = _question_sections(draft_text, question_ids)
    findings: list[dict[str, Any]] = []
    for question in answer_and_claims.get("questions", []):
        question_id = str(question.get("question_id", ""))
        section = sections.get(question_id, "")
        expected = _expected_answer_numbers(question)
        if not expected:
            continue
        for number in expected:
            section_numbers = _numbers_without_question_ids(section, question_id)
            if any(_same_number(value, number) for value in section_numbers):
                continue
            # 期望数字在本问缺失：在答案语境中寻找候选数字（可能是写错的答案）。
            candidates: list[str] = []
            for sentence in _answer_sentences(section):
                for token in re.findall(r"\d+(?:\.\d+)?", sentence.replace(question_id, "")):
                    value = _normalize_number(token)
                    if value is not None and not _same_number(value, number):
                        candidates.append(token)
            candidates = list(dict.fromkeys(candidates))
            if candidates:
                findings.append(
                    {
                        "finding_id": f"AUD-{question_id}-NUM-01",
                        "class": "wrong_number",
                        "location": f"{question_id} 直接答案",
                        "observation": (
                            f"{question_id} 本问应包含正式答案数字 {number:g}，"
                            f"草稿未出现；疑似写成 {', '.join(candidates[:3])}"
                        ),
                        "verdict": "scientific_fact_candidate",
                        "can_continue_without_it": False,
                        "evidence": f"formal={number:g}; draft_candidates={candidates[:5]}",
                        "formal_value": f"{number:g}",
                        "draft_value": candidates[0] if candidates else None,
                    }
                )
            else:
                findings.append(
                    {
                        "finding_id": f"AUD-{question_id}-NUM-02",
                        "class": "missing_formal_answer",
                        "location": f"{question_id} 直接答案",
                        "observation": f"{question_id} 缺少正式答案数字 {number:g}，草稿未覆盖该问答案",
                        "verdict": "advisory",
                        "can_continue_without_it": True,
                        "evidence": f"formal={number:g}",
                    }
                )
    return findings


def extract_strong_claims(draft_text: str) -> list[dict[str, Any]]:
    """按 trigger 关键词提取强主张语句，只作为 claim extraction trigger。"""
    occurrences: list[dict[str, Any]] = []
    for match in re.finditer(r"[^。！？；!?;]+", draft_text):
        sentence = match.group(0).strip()
        triggers = [trigger for trigger in STRONG_TRIGGERS if trigger in sentence]
        if triggers:
            occurrences.append(
                {
                    "sentence": sentence,
                    "triggers": triggers,
                    "position": match.start(),
                    "end": match.end(),
                }
            )
    return occurrences


def resolve_claim(
    occurrence: dict[str, Any],
    answer_and_claims: dict[str, Any],
    *,
    question_id: str | None = None,
) -> dict[str, Any]:
    """把强主张对照主张边界，返回 SUPPORTED / UNSUPPORTED / UNVERIFIED。"""
    triggers = occurrence.get("triggers", [])
    for question in answer_and_claims.get("questions", []):
        if question_id and question.get("question_id") != question_id:
            continue
        forbidden = " ".join(str(item) for item in question.get("forbidden_upgrades", []))
        safe = " ".join(str(item) for item in question.get("safe_claims", []))
        for trigger in triggers:
            if trigger in forbidden:
                return {
                    "question_id": question.get("question_id"),
                    "verdict": "unsupported_claim",
                    "trigger": trigger,
                }
        for trigger in triggers:
            if trigger in safe:
                return {
                    "question_id": question.get("question_id"),
                    "verdict": "supported",
                    "trigger": trigger,
                }
    return {"verdict": "unverified", "trigger": triggers[0] if triggers else ""}


def check_figures(draft_text: str, run_dir: Path) -> list[dict[str, Any]]:
    """草稿中的图引用必须属于 FIGURE_PLAN 允许集合。"""
    root = run_dir.resolve()
    allowed: set[str] = set()
    plan_path = root / "figures/FIGURE_PLAN.json"
    if plan_path.is_file():
        try:
            for figure in load_json(plan_path).get("figures", []):
                if isinstance(figure, dict):
                    if figure.get("figure_id"):
                        allowed.add(str(figure["figure_id"]))
                    if figure.get("latex_label"):
                        allowed.add(str(figure["latex_label"]))
        except ContractError:
            allowed = set()
    used: set[str] = set()
    for match in INCLUDEGRAPHICS_PATTERN.finditer(draft_text):
        used.add(match.group(1).strip())
    for match in REF_PATTERN.finditer(draft_text):
        used.add(match.group(1).strip())
    findings: list[dict[str, Any]] = []
    if not allowed:
        return findings
    for label in sorted(used):
        if not label:
            continue
        base = Path(label).name
        if base not in allowed and label not in allowed:
            findings.append(
                {
                    "finding_id": f"AUD-FIG-{len(findings) + 1:02d}",
                    "class": "unknown_figure",
                    "location": f"图引用 {label}",
                    "observation": f"草稿引用了不在图目录中的图: {label}",
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": f"allowed={sorted(allowed)[:10]}",
                }
            )
    return findings


def _evidence_chain_findings(root: Path) -> list[dict[str, Any]]:
    """并入证据链审计：图必须绑定 production 结果，方法名不得漂移。

    图 26/27 类故障（写作工具自写 refit 生成图，结果与正文正式答案冲突）由
    ``audit_evidence_chain`` 抓出；这里把它的客观失败并入 import audit，使外部
    稿接回时与 wrong_number/unknown_figure 等一样可阻断。
    """
    try:
        from shumozizi.paper.evidence_chain_audit import audit_evidence_chain

        result = audit_evidence_chain(root)
    except (ContractError, OSError, ValueError):
        return []
    return [
        {
            "finding_id": item.get("finding_id", f"EC-{index}"),
            "class": item.get("class", "EVIDENCE_CHAIN_BROKEN"),
            "location": item.get("location", ""),
            "observation": item.get("observation", ""),
            "verdict": item.get("verdict", "objective_failure"),
            "can_continue_without_it": item.get("can_continue_without_it", False),
            "evidence": item.get("evidence", ""),
        }
        for index, item in enumerate(result.get("findings", []))
    ]


def check_citations(draft_text: str, run_dir: Path) -> list[dict[str, Any]]:
    """草稿中的引用键必须属于已登记参考文献。"""
    root = run_dir.resolve()
    allowed: set[str] = set()
    references_path = root / "paper/references.tex"
    if references_path.is_file():
        allowed = set(
            re.findall(r"\\bibitem\{([^}]+)\}", references_path.read_text(encoding="utf-8"))
        )
    cited: set[str] = set()
    for match in CITE_PATTERN.finditer(draft_text):
        cited.update(item.strip() for item in match.group(1).split(",") if item.strip())
    findings: list[dict[str, Any]] = []
    if not allowed:
        return findings
    for key in sorted(cited):
        if key not in allowed:
            findings.append(
                {
                    "finding_id": f"AUD-CIT-{len(findings) + 1:02d}",
                    "class": "unknown_citation",
                    "location": f"引用 {key}",
                    "observation": f"草稿引用了未登记的文献键: {key}",
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": f"allowed={sorted(allowed)[:10]}",
                }
            )
    return findings


def check_formulas(draft_text: str) -> list[dict[str, Any]]:
    """检查 begin/end 环境是否配对。"""
    findings: list[dict[str, Any]] = []
    environments = dict.fromkeys(ENVIRONMENT_PATTERN.findall(draft_text))
    for environment in environments:
        begins = len(re.findall(rf"\\begin\{{{re.escape(environment)}\}}", draft_text))
        ends = len(re.findall(rf"\\end\{{{re.escape(environment)}\}}", draft_text))
        if begins != ends:
            findings.append(
                {
                    "finding_id": f"AUD-FMT-{len(findings) + 1:02d}",
                    "class": "formula_environment",
                    "location": f"\\begin{{{environment}}}",
                    "observation": f"{environment} 环境 begin={begins} 与 end={ends} 不配对",
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": f"begin={begins}; end={ends}",
                }
            )
    return findings


def check_cross_references(draft_text: str) -> list[dict[str, Any]]:
    """草稿中的 \\ref 目标必须存在对应 \\label。"""
    labels = set(LABEL_PATTERN.findall(draft_text))
    references = set(REF_PATTERN.findall(draft_text))
    findings: list[dict[str, Any]] = []
    for label in sorted(references):
        if label not in labels:
            findings.append(
                {
                    "finding_id": f"AUD-XREF-{len(findings) + 1:02d}",
                    "class": "cross_reference",
                    "location": f"\\ref{{{label}}}",
                    "observation": f"草稿引用了未定义的交叉引用: {label}",
                    "verdict": "advisory",
                    "can_continue_without_it": True,
                    "evidence": f"missing_label={label}",
                }
            )
    return findings


def audit_external_draft(run_dir: Path, *, compile_draft: bool = True) -> dict[str, Any]:
    """对外部草稿执行完整导入审计并写入 ``review/import-audit.json``。

    Args:
        run_dir: 当前运行目录。
        compile_draft: 是否实际调用 LaTeX 编译；测试可关闭以隔离绑定逻辑。

    Returns:
        已写入的导入审计文档。

    Raises:
        ContractError: 缺少草稿、缺少 handoff manifest 或 answer-and-claims。
    """
    root = run_dir.resolve()
    manifest_path = root / HANDOFF_MANIFEST_PATH
    if not manifest_path.is_file():
        raise ContractError("缺少 Writer Handoff manifest，无法审计外部草稿")
    answers_path = root / HANDOFF_DIR / ANSWER_AND_CLAIMS_JSON
    if not answers_path.is_file():
        raise ContractError("缺少 answer-and-claims.json，无法做数字/主张绑定")
    payload = read_external_draft(root)
    manifest = load_json(manifest_path)
    answer_and_claims = load_json(answers_path)
    draft_text = payload["draft_text"]
    all_question_ids = [
        str(item.get("question_id", "")) for item in answer_and_claims.get("questions", [])
    ]

    findings: list[dict[str, Any]] = []
    compile_result: dict[str, Any] = {"compiled": True, "engine": None, "errors": []}
    if compile_draft:
        compile_result = compile_external_draft(root)
        if not compile_result["compiled"]:
            findings.append(
                {
                    "finding_id": "AUD-COMPILE-01",
                    "class": "compile_failure",
                    "location": "draft.tex",
                    "observation": "外部草稿无法编译",
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": "; ".join(compile_result.get("errors", []) or [])[:400],
                }
            )
    numbers = extract_numbers(draft_text, answer_and_claims)
    fact_candidates = [
        {
            "finding_id": str(item["finding_id"]),
            "formal_value": item.get("formal_value"),
            "draft_value": item.get("draft_value"),
        }
        for item in numbers
        if item["class"] == "wrong_number"
    ]
    findings.extend(numbers)
    for occurrence in extract_strong_claims(draft_text):
        # 用句子结束位置归属问题：小节标题常与主张句在同一切分块内。
        question_id = _question_for_sentence(
            draft_text, int(occurrence.get("end", occurrence.get("position", 0))), all_question_ids
        )
        resolved = resolve_claim(occurrence, answer_and_claims, question_id=question_id)
        if resolved["verdict"] == "unsupported_claim":
            findings.append(
                {
                    "finding_id": f"AUD-CLM-{len([f for f in findings if f['class'] == 'unsupported_claim']) + 1:02d}",
                    "class": "unsupported_claim",
                    "location": f"{question_id or '全文'} 强主张",
                    "observation": (
                        f"草稿出现越界强主张『{occurrence['triggers'][0]}』: "
                        f"{occurrence['sentence'][:80]}"
                    ),
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": f"trigger={resolved['trigger']}; forbidden_upgrades 覆盖该表达",
                }
            )
    findings.extend(check_figures(draft_text, root))
    findings.extend(check_citations(draft_text, root))
    findings.extend(check_formulas(draft_text))
    findings.extend(check_cross_references(draft_text))
    findings.extend(_evidence_chain_findings(root))

    objective_failures = [
        str(item["finding_id"]) for item in findings if item["verdict"] == "objective_failure"
    ]
    document = {
        "schema_name": "import_audit",
        "schema_version": "1.0",
        "run_id": root.name,
        "handoff_revision": int(manifest.get("handoff_revision", 0)),
        "draft_path": DRAFT_PATH.as_posix(),
        "compiled": compile_result["compiled"],
        "compile_errors": compile_result.get("errors", []),
        "findings": findings,
        "objective_failures": objective_failures,
        "fact_candidates": fact_candidates,
        "generated_at": utc_now(),
    }
    require_valid(document, "import_audit")
    atomic_json(root / AUDIT_PATH, document)
    return document


def classify_fact_candidates(run_dir: Path, audit: dict[str, Any]) -> dict[str, Any]:
    """用 machine binding 确认或驳回数字类 fact candidate。

    正文数字 == 正式结果时驳回（finding 不升级）；不一致时确认为
    ``confirmed_scientific_fact_failure``，该类别后续不可被 Adjudicator 降级。

    Args:
        run_dir: 当前运行目录。
        audit: ``audit_external_draft`` 的返回结果。

    Returns:
        已写入的确认事实失败台账。
    """
    root = run_dir.resolve()
    failures: list[dict[str, Any]] = []
    for candidate in audit.get("fact_candidates", []):
        formal = candidate.get("formal_value")
        draft = candidate.get("draft_value")
        if formal is None or draft is None:
            continue
        if draft == formal:
            continue
        failures.append(
            {
                "finding_id": str(candidate["finding_id"]),
                "claim": f"正式答案数字应为 {formal}，草稿疑似写为 {draft}",
                "formal_value": str(formal),
                "draft_value": str(draft),
                "method": "machine_binding",
                "confirmation_evidence": f"正文 {draft} != 正式结果 {formal}",
                "confirmed_at": utc_now(),
            }
        )
    document = {
        "schema_name": "confirmed_scientific_fact_failure",
        "schema_version": "1.0",
        "run_id": root.name,
        "failures": failures,
        "generated_at": utc_now(),
    }
    require_valid(document, "confirmed_scientific_fact_failure")
    atomic_json(root / CONFIRMED_FAILURE_PATH, document)
    return document


def require_import_audit_passed(run_dir: Path) -> None:
    """要求外部草稿审计无客观失败且无确认事实错误。"""
    root = run_dir.resolve()
    audit_path = root / AUDIT_PATH
    if not audit_path.is_file():
        raise ContractError("尚未执行外部草稿导入审计")
    audit = load_json(audit_path)
    if audit.get("objective_failures"):
        raise ContractError("外部草稿存在客观失败: " + "; ".join(audit["objective_failures"]))
    confirmed_path = root / CONFIRMED_FAILURE_PATH
    if confirmed_path.is_file():
        confirmed = load_json(confirmed_path)
        if confirmed.get("failures"):
            ids = ", ".join(str(item["finding_id"]) for item in confirmed["failures"])
            raise ContractError("外部草稿存在已确认的科学事实错误: " + ids)


def materialize_external_draft(run_dir: Path) -> dict[str, Any]:
    """把已审计的外部稿物化为正式编译入口。

    复制 ``paper/external-author/draft.tex`` 到 ``paper/imported-author/main.tex``
    （外部稿原文件保留），并记录 source draft SHA、import audit SHA 与
    handoff_revision。后续 ``compile_paper`` 在 external 模式下从这个入口编译，
    而不是继续编译内部模板的 ``paper/main.tex``。

    Args:
        run_dir: 当前运行目录。

    Returns:
        已写入的 ``paper/imported-author/receipt.json``。

    Raises:
        ContractError: 导入审计未通过或缺少草稿/manifest。
    """
    root = run_dir.resolve()
    require_import_audit_passed(root)
    draft = root / DRAFT_PATH
    if not draft.is_file():
        raise ContractError("缺少外部草稿 draft.tex")
    manifest_path = root / HANDOFF_MANIFEST_PATH
    if not manifest_path.is_file():
        raise ContractError("缺少 Writer Handoff manifest")
    audit_path = root / AUDIT_PATH
    entry = root / IMPORTED_AUTHOR_ENTRYPOINT
    _copy_external_assets(root, entry.parent)
    document = {
        "schema_name": "imported_author_receipt",
        "schema_version": "1.0",
        "run_id": root.name,
        "entrypoint_path": IMPORTED_AUTHOR_ENTRYPOINT.as_posix(),
        "entrypoint_sha256": sha256_file(entry),
        "source_draft_path": DRAFT_PATH.as_posix(),
        "external_draft_sha256": sha256_file(draft),
        "import_audit_path": AUDIT_PATH.as_posix(),
        "import_audit_sha256": sha256_file(audit_path),
        "handoff_revision": int(load_json(manifest_path).get("handoff_revision", 0)),
        "generated_at": utc_now(),
    }
    require_valid(document, "imported_author_receipt")
    atomic_json(root / IMPORTED_AUTHOR_RECEIPT, document)
    # 外部稿只有物化为并已登记的正式入口后，才允许它驱动候选稿视觉义务。
    # 导入审计阶段仍是 draft_imported，不能让未发布草稿替正式 main 通过闭环。
    from shumozizi.paper.visual_requirements import build_visual_requirements_from_paper

    build_visual_requirements_from_paper(root, source_role="publication")
    return document


def import_external_draft(
    run_dir: Path,
    *,
    draft_source: Path | None = None,
    compile_draft: bool = True,
) -> dict[str, Any]:
    """导入外部草稿：隔离落盘、审计、确认事实候选，并推进 authoring 状态。

    Args:
        run_dir: 当前运行目录。
        draft_source: 外部草稿文件路径；为 ``None`` 时使用已存在的 draft.tex。
        compile_draft: 是否真实编译。

    Returns:
        导入回执（audit + 状态变化）。

    Raises:
        ContractError: 草稿缺失、审计存在客观失败或已确认事实错误。
    """
    root = run_dir.resolve()
    if draft_source is not None:
        draft_path = root / DRAFT_PATH
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        text = draft_source.read_text(encoding="utf-8")
        if not text.strip():
            raise ContractError("外部草稿为空")
        draft_path.write_text(text, encoding="utf-8")
    audit = audit_external_draft(root, compile_draft=compile_draft)
    confirmed = classify_fact_candidates(root, audit)
    freshness = verify_handoff_freshness(root)
    if audit.get("objective_failures") or confirmed.get("failures"):
        status = "blocked"
    elif not freshness["fresh"]:
        mark_authoring_status(root, "needs_rebase")
        status = "needs_rebase"
    else:
        mark_authoring_status(root, "draft_imported")
        # 此时外部稿仍是隔离 draft；视觉回流在 materialize_external_draft
        # 写入正式入口和 receipt 后进行，避免草稿替候选稿提供闭环证据。
        status = "draft_imported"
    return {
        "status": status,
        "audit": audit,
        "confirmed_fact_failures": confirmed.get("failures", []),
        "handoff_fresh": freshness["fresh"],
        "stale_reasons": freshness["reasons"],
    }
