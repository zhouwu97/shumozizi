"""根据当前生产证据规划论文内容，并检查 PDF 是否遗漏必答内容。"""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now
from shumozizi.simple.visualization import require_visualization_complete

PAPER_CONTENT_BLUEPRINT_SCHEMA = "paper_content_blueprint"
PAPER_SUFFICIENCY_REPORT_SCHEMA = "paper_sufficiency_report"
PAPER_CONTENT_BLUEPRINT_PATH = Path("paper/content_blueprint.json")
PAPER_SUFFICIENCY_REPORT_PATH = Path("qa/paper-sufficiency.json")

ELEMENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "abstract": re.compile(r"摘要|\babstract\b", re.IGNORECASE),
    "problem_restatement": re.compile(
        r"问题重述|问题描述|题目重述|\bproblem\s+restatement\b", re.IGNORECASE
    ),
    "assumptions": re.compile(r"假设|\bassumptions?\b", re.IGNORECASE),
    "notation_data_processing": re.compile(
        r"符号|数据处理|\bnotation\b|\bdata\s+processing\b", re.IGNORECASE
    ),
    "shared_model": re.compile(r"共享模型|模型建立|模型与算法|\bshared\s+model\b", re.IGNORECASE),
    "direct_answer": re.compile(r"直接答案|问题答案|\bdirect\s+answer\b", re.IGNORECASE),
    "model_algorithm": re.compile(r"模型|算法|求解|\bmodel\b|\balgorithm\b", re.IGNORECASE),
    "key_results": re.compile(r"关键结果|结果|\bkey\s+results?\b", re.IGNORECASE),
    "verification_boundary": re.compile(
        r"验证|检验|边界|局限|\bvalidation\b|\blimitations?\b", re.IGNORECASE
    ),
    "robustness_or_missing_reason": re.compile(
        r"敏感性|稳健性|鲁棒性|未进行.{0,12}(?:验证|稳健)|缺少.{0,12}(?:验证|稳健)|\brobustness\b|\bsensitivity\b",
        re.IGNORECASE,
    ),
    "conclusion": re.compile(r"结论|\bconclusion\b", re.IGNORECASE),
    "references": re.compile(r"参考文献|\breferences\b", re.IGNORECASE),
    # 逐问论证合同：这些模式只确认论文是否显式承担了相应论证义务，
    # 数学结论本身仍由 scientific review 和 paper blind review 判断。
    "chosen_objective": re.compile(
        r"目标解释|目标函数|优化目标|选定目标|objective\s*(?:semantics|function)", re.IGNORECASE
    ),
    "model_choice_rationale": re.compile(
        r"模型选择理由|选模理由|为何采用|选择该模型|model\s*(?:choice|rationale)", re.IGNORECASE
    ),
    "core_proof_obligations": re.compile(
        r"证明义务|关键证明|正确性条件|不变量|边界条件|proof\s*obligation", re.IGNORECASE
    ),
    "production_result_refs": re.compile(
        r"生产结果|当前结果|结果依据|实验收据|sealed\s*result|result[_ -]?id", re.IGNORECASE
    ),
    "comparison_route": re.compile(
        r"基线|替代路线|备选方法|对比方法|路线比较|comparison|alternative\s*route", re.IGNORECASE
    ),
    "evidence_interpretation": re.compile(
        r"证据解释|结果解释|说明原因|意味着|表明|evidence\s*interpretation", re.IGNORECASE
    ),
    "unproved_boundary": re.compile(
        r"未证明|未证|适用边界|局限|不外推|尚未验证|unproved|limitation|boundary", re.IGNORECASE
    ),
    "source_code_appendix": re.compile(
        r"源码附录|程序源码|完整源码|source\s*code\s*appendix", re.IGNORECASE
    ),
    "matlab_proof_figure_explanation": re.compile(
        r"(?=[\s\S]*(?:MATLAB|Octave))"
        r"(?=[\s\S]*(?:图|figure)\s*\d+)"
        r"(?=[\s\S]*(?:证明|验证|临界|边界|收敛|误差|proof|validation|critical|boundary|convergence|error))",
        re.IGNORECASE,
    ),
}
FIGURE_PATTERN = re.compile(r"(?:图|figure)\s*\d+", re.IGNORECASE)
TABLE_PATTERN = re.compile(r"(?:表|table)\s*\d+", re.IGNORECASE)
CITATION_PATTERN = re.compile(
    r"\[[0-9][0-9,;\- ]*\]|[（(][^（）()]{0,40}(?:19|20)\d{2}[^（）()]{0,40}[）)]"
)
FORMULA_PATTERN = re.compile(r"(?:\$\$|\\\[|\\\(|(?<![<>=])=(?![=>]))")
EXPLANATION_PATTERN = re.compile(
    r"因此|由此|可见|表明|意味着|原因(?:是|在于)|这是因为|"
    r"从而|故而|据此|because|therefore|thus|indicat(?:e|es|ed)|implies?",
    re.IGNORECASE,
)
QUANTITATIVE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|秒|分钟|小时|米|千米|克|千克|元|次|个|"
    r"s|ms|min|h|m|km|kg|yuan)?\b",
    re.IGNORECASE,
)
SENTENCE_PATTERN = re.compile(r"[。！？；.!?;]")
MIN_QUESTION_TEXT_CHARACTERS = 120
MIN_QUESTION_SENTENCES = 3
_HIGH_RISK_FAMILIES = {"geometry_kinematics", "optimization"}
_MATLAB_ENGINES = {"matlab", "octave"}
_GEOMETRY_EVIDENCE_MODES = {"spatial_3d", "orthographic_geometry", "planar_geometry"}
_OPTIMIZATION_EVIDENCE_MODES = {
    "heuristic_trace",
    "proxy_calibration",
    "local_landscape",
    "bound_gap",
    "residual_certificate",
    "enumeration_coverage",
    "analytic_derivation",
}


def _run_output_path(run_dir: Path, path: Path | None, default: Path, label: str) -> Path:
    """解析运行目录内的蓝图或报告位置。"""
    candidate = run_dir / default if path is None else path
    if not candidate.is_absolute():
        candidate = run_dir / candidate
    try:
        relative_inside(run_dir, candidate)
    except ContractError as exc:
        raise ContractError(f"{label}必须写入当前运行目录") from exc
    return candidate.resolve()


def _require_production_state(run_dir: Path) -> dict[str, Any]:
    """确保论文规划不会使用探索性诊断结果。"""
    state = read_simple_state(run_dir)
    if state.get("execution_mode") != "production":
        raise ContractError("探索模式不能生成正式论文内容蓝图")
    return state


def _question_sections(
    question_id: str,
    result_ids: list[str],
    *,
    draft_allowed: bool,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    """生成单个必答问题的直接回答内容约束。"""
    section: dict[str, Any] = {
        "section_id": f"question_{question_id}",
        "kind": "question",
        "question_id": question_id,
        "required": True,
        "draft_allowed": draft_allowed,
        "evidence_result_ids": result_ids,
        "required_elements": [
            "chosen_objective",
            "model_choice_rationale",
            "core_proof_obligations",
            "production_result_refs",
            "comparison_route",
            "evidence_interpretation",
            "unproved_boundary",
            "direct_answer",
        ],
        "argument_contract": {
            "chosen_objective": f"{question_id} 的主目标及聚合口径必须与目标语义收据一致。",
            "model_choice_rationale": "说明模型为何匹配题意、约束和可验证性。",
            "core_proof_obligations": [
                "列出本问必须满足的约束、边界或正确性条件。"
            ],
            "production_result_refs": list(result_ids),
            "comparison_route": "说明至少一条基线或替代路线及比较口径。",
            "evidence_interpretation": "解释当前生产结果支持了什么结论，以及不能支持什么结论。",
            "unproved_boundary": "明确尚未证明、未覆盖或不可外推的边界。",
            "direct_answer": f"直接回答题目要求的 {question_id} 输出，并给出单位。",
        },
    }
    if blocked_reason is not None:
        section["blocked_reason"] = blocked_reason
    return section


def _materialize_source_code_appendix(run_dir: Path) -> list[dict[str, str]]:
    """复制完整 Python/MATLAB 源码，供论文生成器逐文件原文收录。"""
    code_root = run_dir / "code"
    if not code_root.is_dir():
        return []
    bindings: list[dict[str, str]] = []
    for source in sorted(
        path for path in code_root.rglob("*") if path.is_file() and path.suffix.casefold() in {".py", ".m"}
    ):
        try:
            source_text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(f"源码必须是可直接收录的 UTF-8 文本: {source}") from exc
        if not source_text.strip():
            raise ContractError(f"源码文件为空，不能收录到论文附录: {source}")
        relative_source = relative_inside(run_dir, source)
        appendix = run_dir / "paper" / "source_appendix" / source.relative_to(code_root)
        appendix.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, appendix)
        bindings.append(
            {
                "source_path": relative_source.as_posix(),
                "appendix_path": relative_inside(run_dir, appendix).as_posix(),
                "sha256": sha256_file(appendix),
                "source_text": source_text,
            }
        )
    return bindings


def _matlab_required_families(run_dir: Path) -> set[str]:
    """返回当前路由中必须由 MATLAB/Octave 图证明的高风险题型。"""
    if not (run_dir / "state" / "capability-route.json").is_file():
        # 兼容仅测试论文文本结构的旧合成运行；正式 paper 阶段由状态机保证路由存在。
        return set()
    route = require_capability_route(run_dir)
    toolchain = route["toolchain"]
    selected_engines = {
        toolchain.get("production_engine"),
        toolchain.get("independent_engine"),
    }
    if not selected_engines.intersection(_MATLAB_ENGINES):
        return set()
    return set(route["problem_families"]).intersection(_HIGH_RISK_FAMILIES)


def _proof_kinds(contract: Mapping[str, Any]) -> set[str]:
    """根据 Figure Contract 的证据角色判断它承担哪类证明义务。"""
    roles = set(contract.get("evidence_roles", []))
    modes = set(contract.get("evidence_modes", []))
    kinds: set[str] = set()
    if "model_structure" in roles and modes.intersection(_GEOMETRY_EVIDENCE_MODES):
        kinds.add("geometry")
    if roles.intersection({"solver_process", "optimality_evidence"}) and modes.intersection(
        _OPTIMIZATION_EVIDENCE_MODES
    ):
        kinds.add("optimization")
    return kinds


def _materialize_matlab_proof_figures(
    run_dir: Path,
    *,
    required_questions: set[str],
) -> list[dict[str, Any]]:
    """冻结 MATLAB/Octave 证明图的脚本、PNG 与真实执行收据。"""
    required_families = _matlab_required_families(run_dir)
    if not required_families:
        return []
    plan = require_visualization_complete(run_dir)
    bindings: list[dict[str, Any]] = []
    covered: set[str] = set()
    for contract in plan["contracts"]:
        if contract.get("status") != "complete" or contract.get("question_id") not in required_questions:
            continue
        kinds = _proof_kinds(contract)
        needed_kinds = kinds.intersection(
            {"geometry" if item == "geometry_kinematics" else item for item in required_families}
        )
        if not needed_kinds:
            continue
        reference = contract.get("render_receipt")
        if not isinstance(reference, Mapping):
            continue
        receipt_path_value = reference.get("path")
        receipt_hash = reference.get("sha256")
        if not isinstance(receipt_path_value, str) or not isinstance(receipt_hash, str):
            continue
        receipt_path = run_dir / receipt_path_value
        if not receipt_path.is_file() or sha256_file(receipt_path) != receipt_hash:
            continue
        receipt = load_json(receipt_path)
        if receipt.get("engine") not in _MATLAB_ENGINES:
            continue
        script = receipt.get("script", {})
        script_path = script.get("path") if isinstance(script, Mapping) else None
        script_hash = script.get("sha256") if isinstance(script, Mapping) else None
        if (
            not isinstance(script_path, str)
            or not script_path.startswith("code/matlab/")
            or not script_path.casefold().endswith(".m")
            or not isinstance(script_hash, str)
        ):
            continue
        outputs = [
            item
            for item in receipt.get("outputs", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("path"), str)
            and item["path"].casefold().endswith(".png")
            and isinstance(item.get("sha256"), str)
        ]
        if not outputs:
            continue
        for kind in sorted(needed_kinds):
            bindings.append(
                {
                    "proof_kind": kind,
                    "figure_id": contract["figure_id"],
                    "question_id": contract["question_id"],
                    "scientific_question": contract["scientific_question"],
                    "receipt_path": receipt_path_value,
                    "receipt_sha256": receipt_hash,
                    "script_path": script_path,
                    "script_sha256": script_hash,
                    "output_paths": [item["path"] for item in outputs],
                    "output_sha256s": [item["sha256"] for item in outputs],
                }
            )
            covered.add(kind)
    expected = {"geometry" if item == "geometry_kinematics" else item for item in required_families}
    missing = sorted(expected - covered)
    if missing:
        raise ContractError(
            "MATLAB/Octave 已用于高风险路线，但缺少由实际 .m 脚本生成并登记的证明图: "
            + ", ".join(missing)
        )
    return bindings


def build_content_blueprint(
    run_dir: Path,
    *,
    evidence_by_question: Mapping[str, list[str]],
    data_processing_applicable: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """根据 current production 结果建立不依赖固定页数的内容蓝图。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        evidence_by_question: 每个必答问题准备写入论文的结果 ID。
        data_processing_applicable: 是否需要单独的符号/数据处理章节。
        output_path: 可选的运行目录内蓝图输出路径。

    Returns:
        标出每节是否可由当前证据成文的蓝图。

    Raises:
        ContractError: 运行不在 production、证据映射无效或输出越界。
    """
    root = run_dir.resolve()
    state = _require_production_state(root)
    if not isinstance(evidence_by_question, Mapping):
        raise ContractError("evidence_by_question 必须按问题提供结果数组")
    unexpected = sorted(set(evidence_by_question) - set(state["required_questions"]))
    if unexpected:
        raise ContractError("内容蓝图包含非必答问题: " + ", ".join(unexpected))
    result_questions = {
        result["result_id"]: result["question_id"] for result in read_result_index(root)["results"]
    }
    question_sections: list[dict[str, Any]] = []
    all_questions_ready = True
    all_valid_result_ids: list[str] = []
    for question_id in state["required_questions"]:
        supplied = evidence_by_question.get(question_id, [])
        if not isinstance(supplied, list) or any(
            not isinstance(result_id, str) or not result_id for result_id in supplied
        ):
            raise ContractError(f"{question_id} 的论文证据必须是字符串数组")
        valid_ids = [result_id for result_id in supplied if quality_allows_paper(root, result_id)]
        own_valid_ids = [
            result_id for result_id in valid_ids if result_questions.get(result_id) == question_id
        ]
        ready = bool(own_valid_ids)
        all_questions_ready = all_questions_ready and ready
        all_valid_result_ids.extend(valid_ids)
        question_sections.append(
            _question_sections(
                question_id,
                valid_ids,
                draft_allowed=ready,
                blocked_reason=None
                if ready
                else (f"{question_id} 缺少本问 current production/accepted 结果，不能写入题目事实"),
            )
        )
    global_result_ids = list(dict.fromkeys(all_valid_result_ids))
    source_code_appendix = _materialize_source_code_appendix(root)
    matlab_proof_figures = _materialize_matlab_proof_figures(
        root,
        required_questions=set(state["required_questions"]),
    )
    matlab_figure_questions = {item["question_id"] for item in matlab_proof_figures}
    for section in question_sections:
        if section["question_id"] in matlab_figure_questions:
            section["required_elements"].append("matlab_proof_figure_explanation")

    def global_section(
        section_id: str,
        elements: list[str],
        *,
        required: bool = True,
        draft_allowed: bool = True,
        evidence_ids: list[str] | None = None,
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        """创建全局章节的规范记录。"""
        section: dict[str, Any] = {
            "section_id": section_id,
            "kind": "global",
            "required": required,
            "draft_allowed": draft_allowed,
            "evidence_result_ids": list(evidence_ids or []),
            "required_elements": elements,
        }
        if blocked_reason is not None:
            section["blocked_reason"] = blocked_reason
        return section

    result_dependent_reason = "必答问题尚无完整 current production/accepted 证据，不能成文结果事实"
    sections = [
        global_section(
            "abstract",
            ["abstract"],
            draft_allowed=all_questions_ready,
            evidence_ids=global_result_ids,
            blocked_reason=None if all_questions_ready else result_dependent_reason,
        ),
        global_section(
            "problem_restatement_assumptions",
            ["problem_restatement", "assumptions"],
        ),
        global_section(
            "notation_data_processing",
            ["notation_data_processing"],
            required=data_processing_applicable,
        ),
        global_section(
            "shared_model",
            ["shared_model"],
            draft_allowed=all_questions_ready,
            evidence_ids=global_result_ids,
            blocked_reason=None if all_questions_ready else result_dependent_reason,
        ),
        *question_sections,
        global_section(
            "global_robustness_or_missing_reason",
            ["robustness_or_missing_reason"],
            evidence_ids=global_result_ids,
        ),
        global_section(
            "conclusion",
            ["conclusion"],
            draft_allowed=all_questions_ready,
            evidence_ids=global_result_ids,
            blocked_reason=None if all_questions_ready else result_dependent_reason,
        ),
        global_section("references", ["references"]),
        global_section(
            "source_code_appendix",
            ["source_code_appendix"],
            draft_allowed=bool(source_code_appendix),
            blocked_reason=None
            if source_code_appendix
            else "缺少可直接收录到论文附录的 Python/MATLAB 完整源码",
        ),
        {
            "section_id": "appendix",
            "kind": "appendix",
            "required": False,
            "draft_allowed": True,
            "evidence_result_ids": [],
            "required_elements": [],
        },
    ]
    blueprint = {
        "schema_name": PAPER_CONTENT_BLUEPRINT_SCHEMA,
        "schema_version": "2.0",
        "run_id": state["run_id"],
        "state_revision": state["revision"],
        "execution_mode": "production",
        "required_questions": list(state["required_questions"]),
        "data_processing_applicable": data_processing_applicable,
        "source_code_appendix": source_code_appendix,
        "matlab_proof_figures": matlab_proof_figures,
        "sections": sections,
        "generated_at": utc_now(),
    }
    require_valid(blueprint, PAPER_CONTENT_BLUEPRINT_SCHEMA)
    atomic_json(
        _run_output_path(root, output_path, PAPER_CONTENT_BLUEPRINT_PATH, "内容蓝图"), blueprint
    )
    return blueprint


def _question_pattern(question_id: str) -> re.Pattern[str]:
    """生成兼容 Q 编号和中文“第 n 问”的问题标题模式。"""
    escaped = re.escape(question_id)
    number = re.search(r"(\d+)$", question_id)
    alternatives = [rf"\b{escaped}\b"]
    if number is not None:
        value = number.group(1)
        alternatives.extend([rf"第\s*{value}\s*问", rf"问题\s*{value}"])
    return re.compile("|".join(alternatives), re.IGNORECASE)


def _question_segments(text: str, question_id: str, all_question_ids: list[str]) -> list[str]:
    """返回一个题目编号的全部候选文本段。

    PDF 展平文本常在目录、摘要或结论中重复题目编号。保留每个候选段，供调用方
    根据本题所需元素选择正文段，避免将目录条目误判为正文。
    """
    segments: list[str] = []
    for match in _question_pattern(question_id).finditer(text):
        end = len(text)
        for other_id in all_question_ids:
            if other_id == question_id:
                continue
            later = _question_pattern(other_id).search(text, match.end())
            if later is not None:
                end = min(end, later.start())
        segments.append(text[match.end() : end])
    return segments


def _question_segment(
    text: str,
    question_id: str,
    all_question_ids: list[str],
    *,
    required_elements: list[str],
) -> tuple[bool, str]:
    """选择元素覆盖和实质论证最完整的候选正文段。

    目录、摘要和结论可能重复题号。优先选择覆盖元素、包含定量证据和解释且
    正文更长的候选段，使短标签不能抢在真正正文前通过检查。
    """
    segments = _question_segments(text, question_id, all_question_ids)
    if not segments:
        return False, ""

    def score(segment: str) -> tuple[int, int, int, int, int]:
        signals = _argument_signals(segment)
        return (
            sum(_element_detected(element, segment) for element in required_elements),
            int(signals["derivation_or_quantitative_evidence"]),
            int(signals["explanation_present"]),
            int(signals["substantive_body"]),
            int(signals["text_characters"]),
        )

    return True, max(segments, key=score)


def _element_detected(element: str, text: str) -> bool:
    """检查 PDF 文本中是否存在可读的章节或内容标记。"""
    pattern = ELEMENT_PATTERNS.get(element)
    if pattern is None:
        return False
    return pattern.search(text) is not None


def _source_code_present(source_text: str, pdf_text: str) -> bool:
    """逐行确认完整源码文本进入 PDF，容忍排版插入的空白和行号。"""

    def compact(value: str) -> str:
        return re.sub(r"\s+", "", value)

    document = compact(pdf_text)
    source_lines = [compact(line) for line in source_text.splitlines() if compact(line)]
    return bool(source_lines) and all(line in document for line in source_lines)


def _densities(text: str, page_count: int) -> dict[str, int | float]:
    """计算只用于异常诊断的公式、图表、表格和引用密度。"""
    divisor = max(page_count, 1)
    formulas = len(FORMULA_PATTERN.findall(text))
    figures = len(FIGURE_PATTERN.findall(text))
    tables = len(TABLE_PATTERN.findall(text))
    citations = len(CITATION_PATTERN.findall(text))
    return {
        "text_characters": len(text.strip()),
        "formulas": formulas,
        "figures": figures,
        "tables": tables,
        "citations": citations,
        "formulas_per_page": round(formulas / divisor, 4),
        "figures_per_page": round(figures / divisor, 4),
        "tables_per_page": round(tables / divisor, 4),
        "citations_per_page": round(citations / divisor, 4),
    }


def _argument_signals(text: str) -> dict[str, int | bool]:
    """提取逐问正文是否形成最小论证链的可解释信号。"""
    compact = re.sub(r"\s+", "", text)
    text_characters = len(compact)
    sentence_count = len(SENTENCE_PATTERN.findall(text))
    quantitative = bool(
        FORMULA_PATTERN.search(text)
        or QUANTITATIVE_PATTERN.search(text)
        or FIGURE_PATTERN.search(text)
        or TABLE_PATTERN.search(text)
    )
    explanation = EXPLANATION_PATTERN.search(text) is not None
    substantive = bool(
        text_characters >= MIN_QUESTION_TEXT_CHARACTERS
        and sentence_count >= MIN_QUESTION_SENTENCES
    )
    return {
        "text_characters": text_characters,
        "sentence_count": sentence_count,
        "substantive_body": substantive,
        "derivation_or_quantitative_evidence": quantitative,
        "explanation_present": explanation,
    }


def _pdf_text(pdf_path: Path) -> tuple[str, int]:
    """读取 PDF 的文本和页数，交给内容检查而不评价数学正确性。"""
    if not pdf_path.is_file():
        raise ContractError(f"PDF 不存在: {pdf_path}")
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        raise ContractError(f"PDF 无法读取: {exc}") from exc
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def assess_paper_sufficiency(
    blueprint: Mapping[str, Any],
    *,
    pdf_path: Path | None = None,
    pdf_text: str | None = None,
    page_count: int | None = None,
) -> dict[str, Any]:
    """检查 PDF 是否覆盖蓝图中的必答内容，而不按页数设门槛。

    Args:
        blueprint: 已冻结的论文内容蓝图。
        pdf_path: 可选的最终 PDF；未传入时必须提供 ``pdf_text``。
        pdf_text: 用于测试或预览的已提取 PDF 文本，不写入报告。
        page_count: ``pdf_text`` 对应页数；省略时按一页处理。

    Returns:
        包含每题覆盖、内容密度、硬缺失和异常短文警告的报告。

    Raises:
        ContractError: 蓝图不符合协议，或既无 PDF 又无文本。
    """
    document = dict(blueprint)
    require_valid(document, PAPER_CONTENT_BLUEPRINT_SCHEMA)
    if pdf_text is None:
        if pdf_path is None:
            raise ContractError("内容充分性检查需要 PDF 或已提取文本")
        text, actual_page_count = _pdf_text(pdf_path)
    else:
        text = pdf_text
        actual_page_count = 1 if page_count is None else page_count
    if not isinstance(actual_page_count, int) or actual_page_count < 0:
        raise ContractError("page_count 必须为非负整数")

    hard_failures: list[str] = []
    section_coverage: list[dict[str, Any]] = []
    question_coverage: list[dict[str, Any]] = []
    by_question = {
        section.get("question_id"): section
        for section in document["sections"]
        if section["kind"] == "question"
    }
    for section in document["sections"]:
        if section["kind"] == "question":
            continue
        missing = [
            element
            for element in section["required_elements"]
            if not _element_detected(element, text)
        ]
        detected = not missing
        section_coverage.append(
            {
                "section_id": section["section_id"],
                "required": section["required"],
                "draft_allowed": section["draft_allowed"],
                "detected": detected,
                "missing_elements": missing,
            }
        )
        if section["required"] and not section["draft_allowed"]:
            hard_failures.append(
                f"section:{section['section_id']}: {section.get('blocked_reason', '当前证据不允许成文')}"
            )
        elif section["required"] and missing:
            hard_failures.append(f"section:{section['section_id']}: 缺少 {', '.join(missing)}")
    source_bindings = document.get("source_code_appendix", [])
    for binding in source_bindings:
        filename = Path(binding["appendix_path"]).name
        if filename not in text:
            hard_failures.append(f"source-code:{filename}: PDF 源码附录未出现该源码文件")
        elif not _source_code_present(binding["source_text"], text):
            hard_failures.append(f"source-code:{filename}: PDF 仅有文件名或不完整片段，未收录完整源码文本")
    for question_id in document["required_questions"]:
        section = by_question.get(question_id)
        if section is None:
            hard_failures.append(f"question:{question_id}: 内容蓝图缺少必答问题章节")
            question_coverage.append(
                {
                    "question_id": question_id,
                    "heading_detected": False,
                    "elements": {},
                    "argumentation": _argument_signals(""),
                    "complete": False,
                }
            )
            continue
        heading_detected, segment = _question_segment(
            text,
            question_id,
            document["required_questions"],
            required_elements=section["required_elements"],
        )
        elements = {
            element: heading_detected and _element_detected(element, segment)
            for element in section["required_elements"]
        }
        argumentation = _argument_signals(segment) if heading_detected else _argument_signals("")
        complete = bool(
            heading_detected
            and all(elements.values())
            and argumentation["substantive_body"]
            and argumentation["derivation_or_quantitative_evidence"]
            and argumentation["explanation_present"]
            and section["draft_allowed"]
        )
        question_coverage.append(
            {
                "question_id": question_id,
                "heading_detected": heading_detected,
                "elements": elements,
                "argumentation": argumentation,
                "complete": complete,
            }
        )
        section_coverage.append(
            {
                "section_id": section["section_id"],
                "required": section["required"],
                "draft_allowed": section["draft_allowed"],
                "detected": heading_detected,
                "missing_elements": [
                    element for element, detected in elements.items() if not detected
                ],
            }
        )
        if not section["draft_allowed"]:
            hard_failures.append(
                f"question:{question_id}: {section.get('blocked_reason', '当前证据不允许成文')}"
            )
        elif not complete:
            missing = [element for element, detected in elements.items() if not detected]
            if not heading_detected:
                missing.insert(0, "question_heading")
            if not argumentation["substantive_body"]:
                missing.append("substantive_body")
            if not argumentation["derivation_or_quantitative_evidence"]:
                missing.append("derivation_or_quantitative_evidence")
            if not argumentation["explanation_present"]:
                missing.append("explanation")
            hard_failures.append(f"question:{question_id}: 缺少 {', '.join(missing)}")

    warnings: list[str] = []
    densities = _densities(text, actual_page_count)
    if hard_failures and (actual_page_count <= 1 or densities["text_characters"] < 600):
        warnings.append("PDF 异常短且遗漏必答内容；页数本身不作为阻断条件")
    report = {
        "schema_name": PAPER_SUFFICIENCY_REPORT_SCHEMA,
        "schema_version": "2.0",
        "run_id": document["run_id"],
        "status": "pass" if not hard_failures else "blocked",
        "page_count": actual_page_count,
        "densities": densities,
        "section_coverage": section_coverage,
        "question_coverage": question_coverage,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "generated_at": utc_now(),
    }
    require_valid(report, PAPER_SUFFICIENCY_REPORT_SCHEMA)
    return report


def verify_content_blueprint(
    run_dir: Path,
    *,
    blueprint_path: Path | None = None,
) -> dict[str, Any]:
    """复验蓝图声明的题目结果仍然可写入生产论文。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        blueprint_path: 可选的蓝图路径。

    Returns:
        含有效性和错误列表的复验结果。
    """
    root = run_dir.resolve()
    path = _run_output_path(root, blueprint_path, PAPER_CONTENT_BLUEPRINT_PATH, "内容蓝图")
    errors: list[str] = []
    try:
        blueprint = load_json(path)
        require_valid(blueprint, PAPER_CONTENT_BLUEPRINT_SCHEMA)
        state = _require_production_state(root)
        source_bindings = blueprint.get("source_code_appendix")
        if not source_bindings:
            errors.append("内容蓝图缺少必须直接收录到论文的完整 Python/MATLAB 源码")
        else:
            for binding in source_bindings:
                source = root / binding["source_path"]
                appendix = root / binding["appendix_path"]
                if not source.is_file() or not appendix.is_file():
                    errors.append(f"源码附录文件缺失: {binding['source_path']}")
                elif sha256_file(source) != binding["sha256"] or sha256_file(appendix) != binding["sha256"]:
                    errors.append(f"源码附录与当前源码不一致: {binding['source_path']}")
                elif source.read_text(encoding="utf-8") != binding["source_text"]:
                    errors.append(f"源码附录蓝图未冻结完整源码文本: {binding['source_path']}")
        current_matlab_figures = _materialize_matlab_proof_figures(
            root,
            required_questions=set(state["required_questions"]),
        )
        if blueprint.get("matlab_proof_figures", []) != current_matlab_figures:
            errors.append("MATLAB/Octave 证明图蓝图与当前真实渲染收据不一致")
        if blueprint["run_id"] != state["run_id"]:
            errors.append("内容蓝图 run_id 与运行目录不一致")
        if blueprint["state_revision"] > state["revision"]:
            errors.append("内容蓝图来自未来 state revision")
        result_questions = {
            result["result_id"]: result["question_id"]
            for result in read_result_index(root)["results"]
        }
        for section in blueprint["sections"]:
            if section["kind"] != "question" or not section["draft_allowed"]:
                continue
            if not section["evidence_result_ids"] or not all(
                quality_allows_paper(root, result_id)
                for result_id in section["evidence_result_ids"]
            ):
                errors.append(f"{section['section_id']} 的 production 证据已失效")
            elif not any(
                result_questions.get(result_id) == section["question_id"]
                for result_id in section["evidence_result_ids"]
            ):
                errors.append(f"{section['section_id']} 缺少本问 production 证据")
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "blueprint_path": str(path)}


def run_paper_sufficiency_check(
    run_dir: Path,
    *,
    blueprint_path: Path | None = None,
    pdf_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """读取已规划蓝图并写入最终 PDF 的内容充分性报告。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        blueprint_path: 可选的蓝图路径。
        pdf_path: 可选的最终 PDF 路径。
        output_path: 可选的运行目录内报告路径。

    Returns:
        已写入的内容充分性报告。

    Raises:
        ContractError: 蓝图、生产证据或 PDF 不满足检查前提。
    """
    root = run_dir.resolve()
    checked = verify_content_blueprint(root, blueprint_path=blueprint_path)
    if not checked["valid"]:
        raise ContractError("内容蓝图不可用: " + "; ".join(checked["errors"]))
    blueprint = load_json(
        _run_output_path(root, blueprint_path, PAPER_CONTENT_BLUEPRINT_PATH, "内容蓝图")
    )
    report = assess_paper_sufficiency(
        blueprint,
        pdf_path=(root / "paper" / "final.pdf") if pdf_path is None else pdf_path,
    )
    atomic_json(
        _run_output_path(root, output_path, PAPER_SUFFICIENCY_REPORT_PATH, "内容充分性报告"), report
    )
    return report
