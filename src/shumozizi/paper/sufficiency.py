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
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now

PAPER_CONTENT_BLUEPRINT_SCHEMA = "paper_content_blueprint"
PAPER_STRUCTURE_SIGNAL_REPORT_SCHEMA = "paper_structure_signal_report"
PAPER_CONTENT_BLUEPRINT_PATH = Path("paper/content_blueprint.json")
PAPER_STRUCTURE_SIGNAL_REPORT_PATH = Path("qa/paper-structure-signals.json")

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
    "question_inheritance": re.compile(
        r"问题继承|承接前问|沿用前问|共享模型|在前问.{0,16}基础上|"
        r"question\s*inheritance|builds?\s+on\s+(?:the\s+)?previous",
        re.IGNORECASE,
    ),
    "model_choice_rationale": re.compile(
        r"模型选择理由|选模理由|为何采用|选择该模型|model\s*(?:choice|rationale)", re.IGNORECASE
    ),
    "mathematical_object_derivation": re.compile(
        r"数学对象|关键推导|模型推导|状态变量|决策变量|约束推导|"
        r"mathematical\s*object|key\s*derivation|model\s*derivation",
        re.IGNORECASE,
    ),
    "algorithm_steps": re.compile(
        r"算法步骤|求解流程|伪代码|算法流程|迭代步骤|"
        r"algorithm\s*steps?|pseudocode|solution\s*procedure",
        re.IGNORECASE,
    ),
    "core_proof_obligations": re.compile(
        r"模型检验|有效性检验|正确性检验|约束检查|边界条件|"
        r"model\s*validation|validity\s*check", re.IGNORECASE
    ),
    "production_result_refs": re.compile(
        r"结果分析|数值结果|实验结果|比较结果|result\s*analysis|numerical\s*results?",
        re.IGNORECASE,
    ),
    "comparison_route": re.compile(
        r"基线|替代路线|备选方法|对比方法|路线比较|comparison|alternative\s*route", re.IGNORECASE
    ),
    # evidence_interpretation：要求实质解释性语言，而非"表明效果良好"式套话。
    # 删除裸"表明"——"计算表明精度达 0.9"无需解释机制就能触发。
    # 保留或新增需要因果语境的词：意味着、原因在于、这是因为、机制、驱动因素。
    "evidence_interpretation": re.compile(
        r"证据解释|结果解释|说明原因|意味着|原因(?:在于|是)|这是因为|机制|驱动因素|"
        r"evidence\s*interpretation|the\s*reason\s*is",
        re.IGNORECASE,
    ),
    # unproved_boundary：要求逐问的边界声明，而非全局评价节中的通用"局限"套话。
    # 删除裸"局限"——9_evaluation 的"模型缺点：未考虑时间动态性"就能触发。
    # 保留：未证明、适用边界、不外推、尚未验证；新增：结论仅适用、当…改变时。
    "unproved_boundary": re.compile(
        r"未证明|适用边界|不外推|尚未验证|结论仅适用|当.{1,20}改变时|"
        r"unproved|applicable\s*boundary|no\s*extrapolation|boundary\s*condition",
        re.IGNORECASE,
    ),
    "source_code_appendix": re.compile(
        r"源码附录|程序源码|完整源码|source\s*code\s*appendix", re.IGNORECASE
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
DERIVATION_ACTION_PATTERN = re.compile(
    r"(?:关键推导|模型推导).{0,60}(?:给出|得到|推出|导出)|"
    r"(?:定义|令|设).{0,40}(?:变量|状态|目标|约束)|"
    r"(?:key|model)\s+derivation.{0,60}(?:gives?|yields?|derives?)",
    re.IGNORECASE,
)
ALGORITHM_ACTION_PATTERN = re.compile(
    r"(?:先|首先).{2,80}(?:再|然后|随后|继而)|"
    r"(?:初始化|枚举|迭代|递推|更新).{2,80}(?:直到|直至|停止|收敛|完成)|"
    r"步骤\s*[一二三四五六七八九\d]+|"
    r"(?:initialize|iterate|recur).{2,80}(?:until|converge|terminate)",
    re.IGNORECASE,
)
RESULT_COMPARISON_ACTION_PATTERN = re.compile(
    r"(?:相对|相比|较).{0,40}(?:提高|降低|减少|增加|提前|缩短|延长|改善|恶化)"
    r".{0,30}\d|"
    r"compared\s+with.{0,40}(?:increase|decrease|improve|reduce).{0,30}\d",
    re.IGNORECASE,
)
BOUNDARY_ACTION_PATTERN = re.compile(
    r"(?:当|若|如果).{2,60}(?:时|则|需要|不再|重新)|"
    r"(?:仅适用|不外推|适用范围).{2,60}|"
    r"(?:when|if).{2,60}(?:then|requires?|no\s+longer)",
    re.IGNORECASE,
)
QUANTITATIVE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|秒|分钟|小时|米|千米|克|千克|元|次|个|"
    r"s|ms|min|h|m|km|kg|yuan)?\b",
    re.IGNORECASE,
)
SENTENCE_PATTERN = re.compile(r"[。！？；.!?;]")
MINIMUM_BODY_SIGNAL_CHARACTERS = 120
MINIMUM_BODY_SIGNAL_SENTENCES = 3


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
            "question_inheritance",
            "model_choice_rationale",
            "mathematical_object_derivation",
            "algorithm_steps",
            "core_proof_obligations",
            "production_result_refs",
            "comparison_route",
            "evidence_interpretation",
            "unproved_boundary",
            "direct_answer",
        ],
        "argument_contract": {
            "chosen_objective": f"{question_id} 的主目标及聚合口径必须与目标语义收据一致。",
            "question_inheritance": "说明本问从前问继承了什么，以及新增了哪个数学对象或约束。",
            "model_choice_rationale": "说明模型为何匹配题意、约束和可验证性。",
            "mathematical_object_derivation": "定义本问数学对象，并给出从题面到核心关系的必要推导。",
            "algorithm_steps": "给出可复现的求解步骤；复杂算法使用伪代码或等价的清楚流程。",
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

    def score(segment: str) -> tuple[int, int, int, int, int, int]:
        signals = _content_signals(segment)
        return (
            sum(_element_detected(element, segment) for element in required_elements),
            int(signals["argument_action_signal"]),
            int(signals["technical_content_signal"]),
            int(signals["explanation_marker_present"]),
            int(signals["minimum_body_signal"]),
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


def _content_signals(text: str) -> dict[str, int | bool]:
    """提取最低非空壳信号，不判断数学或论证质量。"""
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
        text_characters >= MINIMUM_BODY_SIGNAL_CHARACTERS
        and sentence_count >= MINIMUM_BODY_SIGNAL_SENTENCES
    )
    derivation_action = DERIVATION_ACTION_PATTERN.search(text) is not None
    algorithm_action = ALGORITHM_ACTION_PATTERN.search(text) is not None
    result_comparison_action = RESULT_COMPARISON_ACTION_PATTERN.search(text) is not None
    boundary_action = BOUNDARY_ACTION_PATTERN.search(text) is not None
    return {
        "text_characters": text_characters,
        "sentence_count": sentence_count,
        "minimum_body_signal": substantive,
        "technical_content_signal": quantitative,
        "explanation_marker_present": explanation,
        "derivation_action_present": derivation_action,
        "algorithm_action_present": algorithm_action,
        "result_comparison_action_present": result_comparison_action,
        "boundary_action_present": boundary_action,
        "argument_action_signal": all(
            (
                derivation_action,
                algorithm_action,
                result_comparison_action,
                boundary_action,
            )
        ),
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


def assess_paper_structure_signals(
    blueprint: Mapping[str, Any],
    *,
    pdf_path: Path | None = None,
    pdf_text: str | None = None,
    page_count: int | None = None,
) -> dict[str, Any]:
    """检查 PDF 的逐问结构和最低内容信号，不评价论证质量。

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
            raise ContractError("论文结构信号检查需要 PDF 或已提取文本")
        text, actual_page_count = _pdf_text(pdf_path)
    else:
        text = pdf_text
        actual_page_count = 1 if page_count is None else page_count
    if not isinstance(actual_page_count, int) or actual_page_count < 0:
        raise ContractError("page_count 必须为非负整数")

    missing_required_signals: list[str] = []
    evidence_blockers: list[str] = []
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
            evidence_blockers.append(
                f"section:{section['section_id']}: {section.get('blocked_reason', '当前证据不允许成文')}"
            )
        elif section["required"] and missing:
            missing_required_signals.append(f"section:{section['section_id']}: 缺少 {', '.join(missing)}")
    source_bindings = document.get("source_code_appendix", [])
    for binding in source_bindings:
        filename = Path(binding["appendix_path"]).name
        if filename not in text:
            missing_required_signals.append(f"source-code:{filename}: PDF 源码附录未出现该源码文件")
        elif not _source_code_present(binding["source_text"], text):
            missing_required_signals.append(f"source-code:{filename}: PDF 仅有文件名或不完整片段，未收录完整源码文本")
    for question_id in document["required_questions"]:
        section = by_question.get(question_id)
        if section is None:
            missing_required_signals.append(f"question:{question_id}: 内容蓝图缺少必答问题章节")
            question_coverage.append(
                {
                    "question_id": question_id,
                    "heading_detected": False,
                    "elements": {},
                    "content_signals": _content_signals(""),
                    "structure_signals_complete": False,
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
        content_signals = _content_signals(segment) if heading_detected else _content_signals("")
        requires_argument_actions = {
            "mathematical_object_derivation",
            "algorithm_steps",
            "evidence_interpretation",
            "unproved_boundary",
        }.issubset(section["required_elements"])
        structure_signals_complete = bool(
            heading_detected
            and all(elements.values())
            and content_signals["minimum_body_signal"]
            and content_signals["technical_content_signal"]
            and (not requires_argument_actions or content_signals["argument_action_signal"])
            and section["draft_allowed"]
        )
        question_coverage.append(
            {
                "question_id": question_id,
                "heading_detected": heading_detected,
                "elements": elements,
                "content_signals": content_signals,
                "structure_signals_complete": structure_signals_complete,
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
            evidence_blockers.append(
                f"question:{question_id}: {section.get('blocked_reason', '当前证据不允许成文')}"
            )
        elif not structure_signals_complete:
            missing = [element for element, detected in elements.items() if not detected]
            if not heading_detected:
                missing.insert(0, "question_heading")
            if not content_signals["minimum_body_signal"]:
                missing.append("minimum_body_signal")
            if not content_signals["technical_content_signal"]:
                missing.append("technical_content_signal")
            if requires_argument_actions and not content_signals["argument_action_signal"]:
                missing.append("argument_action_signal")
            missing_required_signals.append(f"question:{question_id}: 缺少 {', '.join(missing)}")

    warnings: list[str] = []
    densities = _densities(text, actual_page_count)
    for item in question_coverage:
        if not item["content_signals"]["explanation_marker_present"]:
            warnings.append(f"question:{item['question_id']}: 未检测到最低解释性语言标记，需由 PDF 盲审判断解释质量")
    if (missing_required_signals or evidence_blockers) and (
        actual_page_count <= 1 or densities["text_characters"] < 600
    ):
        warnings.append("PDF 异常短且遗漏必答内容；页数本身不作为阻断条件")
    mechanical_gate_passed = not missing_required_signals and not evidence_blockers
    report = {
        "schema_name": PAPER_STRUCTURE_SIGNAL_REPORT_SCHEMA,
        "schema_version": "1.0",
        "run_id": document["run_id"],
        "status": "signals_present" if mechanical_gate_passed else "missing_required_signals",
        "mechanical_gate_passed": mechanical_gate_passed,
        "assesses_mathematical_correctness": False,
        "assesses_argument_quality": False,
        "independent_pdf_review_required": True,
        "page_count": actual_page_count,
        "densities": densities,
        "section_coverage": section_coverage,
        "question_coverage": question_coverage,
        "missing_required_signals": missing_required_signals,
        "evidence_blockers": evidence_blockers,
        "warnings": warnings,
        "generated_at": utc_now(),
    }
    require_valid(report, PAPER_STRUCTURE_SIGNAL_REPORT_SCHEMA)
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


def run_paper_structure_signal_check(
    run_dir: Path,
    *,
    blueprint_path: Path | None = None,
    pdf_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """读取蓝图并写入逐问结构与最低内容信号报告。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        blueprint_path: 可选的蓝图路径。
        pdf_path: 可选的最终 PDF 路径。
        output_path: 可选的运行目录内报告路径。

    Returns:
        已写入的论文结构信号报告。

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
    report = assess_paper_structure_signals(
        blueprint,
        pdf_path=(root / "paper" / "final.pdf") if pdf_path is None else pdf_path,
    )
    atomic_json(
        _run_output_path(root, output_path, PAPER_STRUCTURE_SIGNAL_REPORT_PATH, "论文结构信号报告"), report
    )
    return report
