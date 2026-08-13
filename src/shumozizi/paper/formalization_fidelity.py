"""冷启动目标忠实度：把 FORMALIZATION_DIFF 交给独立上下文核验。

FORMALIZATION_DIFF 是模型自述的转换审计，但自述者会倾向把 surrogate 标成
equivalent。冷启动门把核验交给完全不知道求解过程的 reviewer：只给原题、
PROBLEM_CONTRACT 投影与 FORMALIZATION_DIFF，让它逐项核对题面要求的决策变量、
目标量、输出是否在正式目标里保持，拦截"题目问 A 最终答 B"的静默替换。

门的位置在**正式路线比较之前**：目标漂移一旦进入实验，GEE/AFT/Logistic/敏感性
都会按错误目标跑完，成本已付。此门应在那之前拦下。
"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.modeling_units import MODELING_UNITS_PATH


def _project_unit(raw: dict) -> str:
    """把单个建模单元投影为 reviewer 可核验的合同（不含模型/实验细节）。"""
    unit_id = str(raw.get("unit_id", "?"))
    question_id = str(raw.get("question_id", "?"))
    lines = [f"### {unit_id}（{question_id}）"]

    formalization = raw.get("formalization_diff")
    if isinstance(formalization, dict):
        lines.append("**形式化转换（FORMALIZATION_DIFF）**")
        lines.append(f"- 题面原句：{formalization.get('source', '?')}")
        lines.append(f"- 正式目标：{formalization.get('formalized_as', '?')}")
        lines.append(f"- 转换类型：{formalization.get('transformation', '?')}")
        if formalization.get("added_semantics"):
            lines.append(f"- 新增语义：{formalization.get('added_semantics')}")
        if formalization.get("removed_semantics"):
            lines.append(f"- 丢失语义：{formalization.get('removed_semantics')}")
        if formalization.get("equivalence_evidence"):
            lines.append(f"- 等价性说明：{formalization.get('equivalence_evidence')}")

    contract = raw.get("answer_contract")
    if isinstance(contract, dict):
        lines.append("**逐问直接答案合同（PROBLEM_CONTRACT 投影）**")
        if contract.get("required_output"):
            lines.append(f"- 要求输出：{contract['required_output']}")
        if contract.get("decision_scope"):
            lines.append(f"- 决策范围：{contract['decision_scope']}")
        endpoint = contract.get("primary_endpoint")
        if isinstance(endpoint, dict):
            lines.append(f"- 主 endpoint：{endpoint.get('name', '?')}")
            lines.append(f"- endpoint 定义：{endpoint.get('definition', '?')}")
            if endpoint.get("formula"):
                lines.append(f"- endpoint 公式：{endpoint.get('formula')}")

    return "\n".join(lines)


def formalization_fidelity_prompt(run_dir: Path) -> str:
    """生成只读原题与合同投影的独立目标忠实度审查提示。

    Args:
        run_dir: 当前 Competition-First v3.2 运行目录。

    Returns:
        固定提示词，交给完全隔离的新上下文 reviewer。

    Raises:
        ContractError: 运行状态或 MODELING_UNITS 不合法。
    """
    root = run_dir.resolve()
    payload_path = root / MODELING_UNITS_PATH
    if not payload_path.is_file():
        raise ContractError("冷启动门缺少 analysis/MODELING_UNITS.json")
    payload = load_json(payload_path)
    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        raise ContractError("冷启动门需要至少一个建模单元")

    project = "\n\n".join(
        _project_unit(raw) for raw in units if isinstance(raw, dict)
    )
    return (
        "你是完全独立的目标忠实度审查者。你没有参与建模，也不允许读取任何"
        "求解过程、模型实现、实验记录、作者解释或内部审核。你只凭下面的原题"
        "与合同投影，逐项核验正式目标是否忠实于题面。\n\n"
        f"运行目录（只允许读该目录下的题面 problem/）：{root}\n"
        "允许读取：\n"
        f"- {root / 'problem'}（原题与附件）\n"
        "禁止读取：code/、results/、MODELING_UNITS.json 之外的任何文件、"
        "任何作者解释。\n\n"
        "以下是每个问题的合同投影（FORMALIZATION_DIFF + 直接答案合同）：\n\n"
        f"{project}\n\n"
        "只回答以下问题，逐问填写：\n"
        "1. 题面要求的每个决策变量还在不在正式目标里？\n"
        "2. 题面要求优化的量是否仍是最终目标？有没有从'最小化 X'变成"
        "'满足 Y 后最早/最大/最小 Z'？\n"
        "3. 题面要求的每个输出是否都会返回？有没有输出被替换成别的？\n"
        "4. 是否新增了一个题面没有的阈值或约束，且它控制了最终答案？\n"
        "5. 转换类型声明与题面原句是否一致？（若标 equivalent 但实际替换了目标，"
        "必须指出）\n\n"
        "返回 JSON：字段为 question_id、verdict（fidelity_ok / "
        "surrogate_with_evidence / silent_replacement）、missing_decision_variables、"
        "replaced_objective、missing_outputs、added_threshold、evidence。"
        "verdict=silent_replacement 时必须说明被替换的原目标与替换后的目标。"
    )
