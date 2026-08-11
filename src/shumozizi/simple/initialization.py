"""初始化 Competition-First v3.1/v3.2 运行目录。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.simple.state import require_simple_state, utc_now

SIMPLE_DIRECTORIES = (
    "problem/attachments",
    "state",
    "reports",
    "code",
    "results/raw",
    "results/evidence",
    "analysis",
    "figures/current",
    "figures/work",
    "figures/archive",
    "figures/promotions",
    "figures/reviews",
    "paper/sections",
    "paper/generated",
    "paper/submission",
    "review/red_team_artifacts",
    "review/tasks",
    "review/packet/objective-semantics",
    "review/packet/scientific",
    "review/packet/paper-blind",
    "qa",
)


def safe_simple_run_id(value: str) -> str:
    """将运行 ID 规整为不会逃逸 ``runs/`` 的目录名。

    Args:
        value: 用户提供的运行 ID。

    Returns:
        仅由安全字符构成的运行 ID。

    Raises:
        ContractError: 规整后为空。
    """
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not normalized:
        raise ContractError("run_id 不能为空")
    return normalized


def _copy_problem(problem_path: Path, run_dir: Path) -> dict[str, str]:
    """复制只读题面和附件，避免后续工作修改原始输入。

    Args:
        problem_path: 题面文件或包含题面、附件的目录。
        run_dir: 新建 v3 运行目录。

    Returns:
        与输入有关的产物路径。

    Raises:
        FileNotFoundError: 输入题面不存在。
    """
    source = problem_path.resolve()
    if not source.exists():
        raise FileNotFoundError(f"题面路径不存在: {source}")
    problem_dir = run_dir / "problem"
    artifacts: dict[str, str] = {}
    if source.is_file():
        target = problem_dir / f"statement{source.suffix or '.md'}"
        shutil.copy2(source, target)
        artifacts["statement"] = target.relative_to(run_dir).as_posix()
        return artifacts

    candidates = sorted(
        path
        for path in source.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf", ".docx"}
    )
    statement = next(
        (path for path in candidates if path.stem.lower() in {"statement", "problem", "题目"}),
        candidates[0] if candidates else None,
    )
    if statement is not None:
        target = problem_dir / f"statement{statement.suffix}"
        shutil.copy2(statement, target)
        artifacts["statement"] = target.relative_to(run_dir).as_posix()
    attachments = problem_dir / "attachments"
    for item in source.rglob("*"):
        if not item.is_file() or item == statement:
            continue
        relative = item.relative_to(source)
        target = attachments / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
    return artifacts


def _paper_blueprint_template(question_ids: list[str]) -> str:
    """生成与论证覆盖解析器同源的作者蓝图模板。"""
    cards: list[str] = []
    for question_id in question_ids:
        cards.append(
            f"## {question_id} 完整性卡\n\n"
            "- **题面要求**：待填写。\n"
            "- **继承**：待填写。\n"
            "- **新增困难**：待填写。\n"
            "- **数学对象**：待填写。\n"
            "- **建模依据**：待填写。\n"
            "- **关键推导**：待填写。\n"
            "- **求解过程**：待填写。\n"
            "- **主结果**：待填写。\n"
            "- **结果解释**：待填写。\n"
            "- **机制或规律**：待填写。\n"
            "- **验证**：待填写。\n"
            "- **适用边界**：待填写。\n"
            "- **直接答案**：待填写。\n\n"
            "核心问题另填：\n\n"
            "### 要支持的判断\n\n待填写。\n\n"
            "### 计算证据\n\n待填写。\n\n"
            "### 竞争解释\n\n待填写。"
        )
    return (
        "# PAPER_BLUEPRINT\n\n"
        "## 全篇中心判断\n\n"
        "待填写：一句话说明统一数学对象、主答案、关键规律与证据边界。\n\n"
        "## 全局证据蒸馏\n\n"
        "### 主要结论 1\n\n"
        "- **结论**：待填写。\n"
        "- **数学原因**：待填写。\n"
        "- **决定性证据**：待填写。\n"
        "- **竞争解释**：待填写。\n"
        "- **适用边界**：待填写。\n\n"
        "## 跨问题论证链与连续成文\n\n"
        "待填写：各问继承的对象、新增困难、章节作用以及连续论证顺序。\n\n"
        "## v3.4 长篇首稿交接\n\n"
        "先读取生成的 RESEARCH_PACKAGE.md 与 AUTHOR_BRIEF.md，再写长篇科学首稿。"
        "章节与问题合并方式由作者根据共享数学对象、关键困难和证据节奏决定；"
        "不得把完整性检查项机械转写成正文小节。\n\n"
        "## 正文与附录边界\n\n"
        "- **正文保留**：待填写。\n"
        "- **附录或控制层**：待填写。\n\n"
        "## 摘要主线\n\n"
        "按“核心困难—统一结构—关键方法—主要结果—机制—边界”规划，禁止逐问报账。\n\n"
        + ("\n\n".join(cards) if cards else "## 各问完整性卡\n\n待题面审计后逐问填写。")
        + "\n\n## 贡献（最多三项）\n\n"
        "待填写：只写由当前模型、实验或洞察支持的贡献。\n\n"
        "## 图表与篇幅\n\n"
        "按视觉机会池规划模型理解、决定性证据、机制、边界和决策表达；"
        "不预设一问一图或 hero 图，纯解析豁免必须说明替代表达。\n"
    )


def _paper_review_template(run_id: str) -> str:
    """生成可由审核导入器原子维护的批量返修模板。"""
    return (
        "# PAPER_REVIEW\n\n"
        "## 评委冷读\n\n"
        "只以评委身份阅读完整论文，不先读取日志、manifest、哈希账本或工作流状态。"
        "先用三句话复述论文解决了什么、最强数学判断是什么、为什么可信；"
        "再检查三分钟内能否找到逐问直接答案、中央推导是否充分、主图是否解释机制，"
        "参考文献是否覆盖实际使用的核心方法与验证且在正文具体位置被引用，"
        "以及软件说明、运行记录和审核语言是否侵入正文。\n\n"
        "## 返修原则\n\n"
        "只保留最能改变科学结论、论证理解或评委判断的返修项，并明确区分 science、"
        "argument、style、figure 和 render。每项 finding 必须有验收测试、停止条件和关闭证据；"
        "P0/P1 不得仅接受风险或延期。自然语言负责提高评审质量，以下 JSON 负责系统闭环。\n\n"
        "<!-- PAPER_REVIEW_FINDINGS:START -->\n"
        "```json\n"
        "{\n"
        '  "schema_name": "paper_review",\n'
        '  "schema_version": "2.0",\n'
        f'  "run_id": "{run_id}",\n'
        '  "findings": []\n'
        "}\n"
        "```\n"
        "<!-- PAPER_REVIEW_FINDINGS:END -->\n"
    )


def _paper_citation_plan_template() -> str:
    """生成避免文献过少或只列不引的论文引用交接模板。"""
    return (
        "# CITATION_PLAN\n\n"
        "这不是结果证据表，也不能用来替代当前运行的实验。只登记实际阅读并在正文中承担明确作用的可核验来源。\n\n"
        "## 推荐紧凑范围\n\n"
        "正文与参考文献合计先按 6--12 条规划；数量只是写作密度提示，不是获奖证明。每条文献必须至少在正文一个具体判断后被引用。\n\n"
        "## 来源分配\n\n"
        "- **题型与领域背景（1--2 条）**：说明问题背景、统计单位或领域约束。\n"
        "- **核心数学方法（2--4 条）**：只引用实际采用的优化、统计、仿真、几何或数据处理方法。\n"
        "- **验证与不确定性（1--3 条）**：支持 bootstrap、区间、稳健性、误差或评价指标的定义。\n"
        "- **可选扩展（0--3 条）**：只有确实帮助解释模型选择、机制或边界时才加入。\n\n"
        "## 正文绑定表\n\n"
        "类别只使用 `background`、`core_method`、`validation`、`uncertainty` 或 `extension`。\n\n"
        "| citation key | 类别 | 来源与可核验信息 | 正文位置 | 支持的具体判断 |\n"
        "|---|---|---|---|---|\n"
        "| 待填写 | core_method | 待填写 | 第 X 节/公式/图后段 | 待填写 |\n\n"
        "禁止：同题答案、题解、现成数值结论、奖项评价或未实际阅读的条目；不要为了凑数量堆砌引用。\n"
    )


def initialize_simple_run(
    repo_root: Path,
    run_id: str,
    *,
    problem_path: Path | None = None,
    competition: str = "",
    problem_id: str = "",
    required_questions: list[str] | None = None,
    total_hours: float | None = None,
    token_soft_cap: int | None = None,
    workflow_version: str = "3.1",
    require_web_review: bool = False,
    paper_draft_mode: str | None = None,
    initial_execution_mode: str = "production",
    execution_policy: str = "legacy-production-v1",
    quality_policy: str = "legacy",
) -> Path:
    """创建可独立恢复的 v3 运行目录。

    Args:
        repo_root: 项目仓库根目录。
        run_id: 运行 ID。
        problem_path: 可选的题面文件或目录。
        competition: 竞赛类型或名称。
        problem_id: 题目编号。
        required_questions: 已知必答问题列表。
        total_hours: 可选的总时间预算。
        token_soft_cap: 可选的 token 软上限。
        workflow_version: ``3.1`` 保持兼容；``3.2`` 启用建模单元和 LaTeX 主链。
        require_web_review: 是否把网页版 GPT 人工新对话审核设为必需交付步骤。
        paper_draft_mode: 可选首稿模式；直接调用旧 Python API 未指定时保持
            reviewable fallback 兼容，新 CLI 默认显式传入长篇科学首稿。
        initial_execution_mode: 初始实验用途；旧 API 默认保持 production 兼容。
        execution_policy: 执行策略；新 v3.2 CLI 使用风险自适应策略。
        quality_policy: 运行开始即冻结的论文质量合同；新 CLI 使用 competition-quality-v1。

    Returns:
        新建运行目录。

    Raises:
        ContractError: 运行目录逃逸或状态不合法。
        FileExistsError: 指定运行目录已经包含内容。
    """
    root = repo_root.resolve()
    if workflow_version not in {"3.1", "3.2"}:
        raise ContractError("workflow_version 必须为 3.1 或 3.2")
    if paper_draft_mode not in {None, "longform_scientific_draft", "reviewable_draft"}:
        raise ContractError("paper_draft_mode 必须为 longform_scientific_draft 或 reviewable_draft")
    if initial_execution_mode not in {"production", "exploration"}:
        raise ContractError("initial_execution_mode 必须为 production 或 exploration")
    if execution_policy not in {"legacy-production-v1", "risk-adaptive-v1"}:
        raise ContractError("execution_policy 必须为 legacy-production-v1 或 risk-adaptive-v1")
    if workflow_version != "3.2" and execution_policy == "risk-adaptive-v1":
        raise ContractError("risk-adaptive-v1 仅适用于 v3.2 运行")
    if quality_policy not in {"legacy", "competition-quality-v1"}:
        raise ContractError("quality_policy 必须为 legacy 或 competition-quality-v1")
    if workflow_version != "3.2" and quality_policy != "legacy":
        raise ContractError("competition-quality-v1 仅适用于 v3.2 运行")
    identifier = safe_simple_run_id(run_id)
    runs_root = (root / "runs").resolve()
    run_dir = (runs_root / identifier).resolve()
    if runs_root not in run_dir.parents:
        raise ContractError("运行目录越过 runs/ 边界")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"运行目录已存在且非空: {run_dir}")
    for relative in SIMPLE_DIRECTORIES:
        (run_dir / relative).mkdir(parents=True, exist_ok=True)

    artifacts = _copy_problem(problem_path, run_dir) if problem_path else {}
    now = utc_now()
    state: dict[str, Any] = {
        "schema_version": workflow_version,
        "run_id": identifier,
        "workflow": f"competition-first-v{workflow_version}",
        "phase": "analysis",
        "execution_mode": initial_execution_mode,
        "execution_policy": execution_policy,
        "revision": 0,
        "paper_render_revision": 0,
        "paper_reviewed_revision": 0,
        "layout_audited_revision": 0,
        "argument_revision": 0,
        "render_revision": 0,
        "reviewed_argument_revision": 0,
        "layout_audited_render_revision": 0,
        "competition": competition,
        "problem_id": problem_id,
        "required_questions": required_questions or [],
        "current_question": None,
        "completed_questions": [],
        "selected_route": None,
        "fallback_route": None,
        "artifacts": artifacts,
        "time_budget": {"total_hours": total_hours, "remaining_hours": total_hours},
        "token_budget": {"soft_cap": token_soft_cap, "used_estimate": None},
        "updated_at": now,
    }
    require_simple_state(state)
    atomic_json(run_dir / "state" / "run.json", state)
    atomic_json(
        run_dir / "results" / "index.json",
        {"schema_version": "1.0", "run_id": identifier, "results": []},
    )
    atomic_json(
        run_dir / "results" / "quality.json",
        {"schema_version": "3.0", "run_id": identifier, "assessments": []},
    )
    atomic_json(
        run_dir / "figures" / "index.json",
        {"schema_version": "1.2", "run_id": identifier, "figures": []},
    )
    (run_dir / "state" / "DECISIONS.md").write_text(
        "# 决策记录\n\n"
        "## 题意解释\n- 待补充。\n\n"
        "## 路线选择\n- 先完成 baseline 与区分性 probe。\n- 主路线：待确定。\n- fallback：待确定。\n- 放弃路线及原因：待确定。\n",
        encoding="utf-8",
        newline="\n",
    )
    if workflow_version == "3.2":
        from shumozizi.simple.delivery import initialize_delivery_control

        initialize_delivery_control(
            run_dir,
            root,
            total_hours=total_hours,
            require_web_review=require_web_review,
            started_at=now,
        )
        atomic_json(
            run_dir / "analysis" / "MODELING_UNITS.json",
            {
                "schema_version": "1.4",
                "run_id": identifier,
                "semantic_reconstructions": [],
                "research_story": {
                    "central_tension": "待填写：题目的核心矛盾与统一研究主线。",
                    "central_mathematical_object": "待填写：贯穿全文的共享状态、判定器或概率对象。",
                    "question_progression": [],
                },
                "units": [],
            },
        )
        (run_dir / "paper" / "PAPER_BLUEPRINT.md").write_text(
            _paper_blueprint_template(list(required_questions or [])),
            encoding="utf-8",
            newline="\n",
        )
        (run_dir / "paper" / "PAPER_REVIEW.md").write_text(
            _paper_review_template(identifier),
            encoding="utf-8",
            newline="\n",
        )
        (run_dir / "paper" / "CITATION_PLAN.md").write_text(
            _paper_citation_plan_template(),
            encoding="utf-8",
            newline="\n",
        )
        # v3.4 的作者输入先落成空素材池和问题故事板；空池不会伪造结果，
        # 但能让后续编排明确知道哪些科学内容仍未交接给论文层。
        from shumozizi.paper.materials import build_material_pool
        from shumozizi.paper.policy import freeze_workflow_snapshot, refresh_policy_state
        from shumozizi.paper.storyboard import build_research_storyboard

        build_material_pool(run_dir)
        build_research_storyboard(run_dir)
        from shumozizi.simple.visual_opportunities import build_visual_opportunity_pool

        build_visual_opportunity_pool(run_dir)
        refresh_policy_state(run_dir)
        freeze_workflow_snapshot(run_dir, quality_policy=quality_policy)
        atomic_json(
            run_dir / "paper" / "draft-mode.json",
            {
                "schema_version": "1.0",
                "run_id": identifier,
                # 直接调用旧 API 不改变 v3.2 迁移测试；新 CLI 会明确传入长篇模式。
                "default_mode": paper_draft_mode or "reviewable_draft",
            },
        )
    return run_dir
