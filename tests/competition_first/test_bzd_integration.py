"""验证 BZD 数学建模 Skills 的真实加载、隔离打擂契约、无伪造字段与清洗合流逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.challenger.bzd_skill_bundle import format_bzd_prompt, load_bzd_skill
from scripts.challenger.run_bzd_challenger import (
    build_isolated_challenger_prompt,
    extract_challenger_routes,
    import_challenger_routes_to_competition,
    prepare_bzd_isolation_packet,
    record_challenger_execution,
    validate_challenger_candidates,
)
from scripts.challenger.run_bzd_translator import (
    build_translator_prompt,
    slice_problem_into_sentence_units,
    validate_bzd_ledger,
)
from scripts.review.sanitize_bzd_review import (
    extract_findings_from_review,
    import_bzd_findings_to_repair_loop,
    sanitize_and_export,
    sanitize_bzd_text,
)
from scripts.review.show_bzd_judge_prompt import (
    build_judge_prompt,
    build_rubric_prompt,
)
from shumozizi.paper.repair_loop import close_repair_directive
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.results import read_result_index

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_bzd_vendor_asset_structure_and_unverified_license() -> None:
    """vendor/bzd-math-modeling 必须固定 commit，标记真实 unverified 许可且不伪造 LICENSE 文件。"""
    vendor_root = REPO_ROOT / "vendor" / "bzd-math-modeling"
    assert vendor_root.is_dir()

    source_path = vendor_root / "SOURCE.json"
    assert source_path.is_file()
    source_meta = json.loads(source_path.read_text(encoding="utf-8"))

    assert source_meta["repository"] == "https://github.com/BZDmathclub/bzd-math-modeling-skills"
    assert len(source_meta["commit"]) == 40
    assert source_meta["license"] == "unverified"
    assert source_meta["license_files"] == []
    assert set(source_meta["imported_paths"]) == {
        "bzd-problem-translator",
        "bzd-modeling-ideas",
        "bzd-review-paper",
    }
    # 确保本地未虚假注入未经授权的 LICENSE 文件
    assert not (vendor_root / "LICENSE").exists()

    # 检查三个子技能目录与核心文件
    for skill_name in source_meta["imported_paths"]:
        skill_dir = vendor_root / skill_name
        assert skill_dir.is_dir()
        assert (skill_dir / "SKILL.md").is_file()


def test_bzd_bridge_skill_registered_in_agents_skills() -> None:
    """.agents/skills/mathmodel-bzd-challenger 必须具备合规的 frontmatter 与 openai.yaml。"""
    skill_dir = REPO_ROOT / ".agents" / "skills" / "mathmodel-bzd-challenger"
    assert skill_dir.is_dir()

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\n")
    _, frontmatter_text, _ = skill_md.split("---", maxsplit=2)
    frontmatter = yaml.safe_load(frontmatter_text)

    assert frontmatter["name"] == "mathmodel-bzd-challenger"
    assert len(frontmatter["description"].strip()) >= 20

    openai_yaml = (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
    interface = yaml.safe_load(openai_yaml)["interface"]
    assert "$mathmodel-bzd-challenger" in interface["default_prompt"]
    assert interface["display_name"].strip()


def test_bzd_prompt_actually_contains_upstream_skill_reference_content() -> None:
    """Prompt 必须真实加载上游原版 SKILL.md 与 references 知识库，杜绝本地手写缩水版。"""
    bundle = load_bzd_skill("bzd-modeling-ideas")
    assert "bzd-modeling-ideas" in bundle["skill_md"]
    assert "integrated-modeling-patterns.md" in bundle["references"]
    assert len(bundle["references"]["integrated-modeling-patterns.md"]) > 500

    prompt = format_bzd_prompt(
        skill_name="bzd-modeling-ideas",
        task_context="【测试赛题上下文】",
        local_rules="【测试本地规则】",
        required_references=["integrated-modeling-patterns.md", "strategy-output-standard.md"],
    )
    assert "【上游 BZD 原版 Skill: bzd-modeling-ideas】" in prompt
    assert "【上游 Required References" in prompt
    assert "integrated-modeling-patterns.md" in prompt
    assert "strategy-output-standard.md" in prompt
    assert "【shumozizi 本地覆盖规则" in prompt


def test_bzd_isolated_packet_contains_problem_and_attachments_and_cleans_stale_files(tmp_path: Path) -> None:
    """物理隔离 Packet 必须复制题面与多格式附件，并在重建时清空旧文件，严格屏蔽本地已选路线。"""
    run_dir = tmp_path / "run_01"
    problem_dir = run_dir / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025 A题 太阳能电池优化\n\n背景描述...", encoding="utf-8")
    (problem_dir / "data.csv").write_text("t,power,voltage\n1,10.5,12.0\n2,11.2,12.1\n", encoding="utf-8")
    (problem_dir / "old_stale_file.xlsx").write_text("dummy old excel", encoding="utf-8")

    # 模拟本地已有解题上下文（污染源）
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "analysis" / "ROUTE_COMPETITION.md").write_text("本地已选主路线 A: 遗传算法", encoding="utf-8")
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "code" / "main.py").write_text("print('local solution')", encoding="utf-8")
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "results" / "answer.json").write_text("{\"score\": 99.5}", encoding="utf-8")

    # 首次构建
    packet_dir = prepare_bzd_isolation_packet(run_dir)
    assert packet_dir.is_dir()
    assert (packet_dir / "problem" / "old_stale_file.xlsx").is_file()

    # 模拟题面更新：删除了 old_stale_file.xlsx，新增 attachment2.xlsx
    (problem_dir / "old_stale_file.xlsx").unlink()
    (problem_dir / "attachment2.xlsx").write_text("new excel", encoding="utf-8")

    # 第二次构建：验证 stale-file 被彻底清空
    packet_dir_2 = prepare_bzd_isolation_packet(run_dir)
    assert not (packet_dir_2 / "problem" / "old_stale_file.xlsx").exists()
    assert (packet_dir_2 / "problem" / "attachment2.xlsx").is_file()
    assert (packet_dir_2 / "INPUT_MANIFEST.md").is_file()

    # 确保绝不包含本地污染源
    assert not (packet_dir_2 / "ROUTE_COMPETITION.md").exists()
    assert not (packet_dir_2 / "code").exists()
    assert not (packet_dir_2 / "results").exists()

    # 检查生成的隔离 Prompt，验证包含 Excel 检视指引且无本地路线泄露
    prompt = build_isolated_challenger_prompt(run_dir)
    assert "2025 A题 太阳能电池优化" in prompt
    assert "[CSV附件] data.csv" in prompt
    assert "[Excel附件] attachment2.xlsx" in prompt
    assert "本地已选主路线 A" not in prompt
    assert "local solution" not in prompt


def test_bzd_challenger_execution_receipt_recorded(tmp_path: Path) -> None:
    """独立上下文 Challenger 执行必须记录 thread ID 与无父上下文凭证。"""
    receipt_file = record_challenger_execution(tmp_path, thread_id="thread_bzd_challenger_9988", provider="codex")
    assert receipt_file.is_file()
    data = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert data["role"] == "bzd_modeling_challenger"
    assert data["raw_thread_id"] == "thread_bzd_challenger_9988"
    assert data["parent_context_inherited"] is False


def test_bzd_extractor_never_fabricates_missing_science_fields(tmp_path: Path) -> None:
    """严禁编造科学字段：若 BZD 输出未包含 endpoint、假设或求解器，提取器必须返回 None / []，绝不允许伪造 formal_target_q1。"""
    candidates_path = tmp_path / "analysis" / "external" / "bzd-route-candidates.md"
    candidates_path.parent.mkdir(parents=True)

    incomplete_text = """# 建模方案候选
### 1. 整题建模主线
骨干网络...
### 2. 跨问题联动链
```mermaid
flowchart LR
  A --> B
```
### 3. 全文统一建模口径
口径...
### 4. 分问题求解思路
#### 4.1 问题一求解思路
##### 4.1.3 可用模型及选型比较
- 推荐模型：基于状态转移的时空规划模型
- 选用理由：结构契合
- 备选模型：启发式贪心分配
"""
    candidates_path.write_text(incomplete_text, encoding="utf-8")
    routes = extract_challenger_routes(candidates_path)
    assert len(routes) == 2

    r1 = routes[0]
    assert r1["question"] == "Q1"
    assert r1["name"] == "基于状态转移的时空规划模型"
    # 核心防回归断言：绝对不能出现硬编码的 formal_target_q1 或假假设！
    assert r1["endpoint"] is None
    assert "formal_target" not in str(r1["endpoint"])
    assert r1["assumptions"] == []
    assert r1["solver"] is None
    assert r1["failure_risk"] is None


def test_bzd_extractor_parses_json_and_markdown_routes_and_merges_competition(tmp_path: Path) -> None:
    """提取器能够解析末尾结构化 JSON 块并合流写入 ROUTE_COMPETITION.md。"""
    candidates_path = tmp_path / "analysis" / "external" / "bzd-route-candidates.md"
    candidates_path.parent.mkdir(parents=True)

    candidates_text = """# 建模方案候选
### 1. 整题建模主线
主线...
### 2. 跨问题联动链
```mermaid
flowchart LR
  A --> B
```
### 3. 全文统一建模口径
口径...
### 4. 分问题求解思路
#### 4.1 问题一求解思路
##### 4.1.3 可用模型及选型比较
- 推荐模型：连续时空非线性规划 (IPOPT)

```json
[
  {
    "question": "Q1",
    "route_id": "bzd-q1-01",
    "name": "连续时空非线性规划 (IPOPT)",
    "role": "challenger_primary",
    "mathematical_structure": "continuous non-linear optimization",
    "endpoint": "min(total_flight_time)",
    "assumptions": ["连续可微航迹", "无突变风场"],
    "required_data": ["初末航路点", "地形高程"],
    "solver": "IPOPT / CasADi",
    "distinguishing_probe": "小规模网格 NLP vs 离散枚举对照",
    "failure_risk": "非凸地形可能陷入局部极小"
  }
]
```
"""
    candidates_path.write_text(candidates_text, encoding="utf-8")
    valid, issues = validate_challenger_candidates(candidates_path)
    assert valid, issues

    routes = extract_challenger_routes(candidates_path)
    assert len(routes) == 1
    r = routes[0]
    assert r["question"] == "Q1"
    assert r["route_id"] == "bzd-q1-01"
    assert r["endpoint"] == "min(total_flight_time)"
    assert r["solver"] == "IPOPT / CasADi"
    assert "无突变风场" in r["assumptions"]

    # 验证合流入 ROUTE_COMPETITION.md
    comp_file = import_challenger_routes_to_competition(tmp_path, candidates_path)
    assert comp_file.is_file()
    comp_text = comp_file.read_text(encoding="utf-8")
    assert "## BZD 独立 Challenger 候选路线（已合流入擂台）" in comp_text
    assert "`bzd-q1-01`" in comp_text
    assert "`min(total_flight_time)`" in comp_text
    assert "IPOPT / CasADi" in comp_text or "continuous non-linear optimization" in comp_text


def test_bzd_challenger_route_reaches_exploration_experiment(tmp_path: Path) -> None:
    """端到端打擂闭环：BZD 候选路线能够通过 execute_simple_experiment 真实执行 exploration 实验并记录 source_route_id。"""
    problem_file = tmp_path / "problem" / "problem.md"
    problem_file.parent.mkdir(parents=True, exist_ok=True)
    problem_file.write_text("# 测试赛题\n", encoding="utf-8")

    run_dir = initialize_simple_run(
        tmp_path,
        run_id="run_bzd_exp",
        problem_path=problem_file,
        required_questions=["Q1"],
        workflow_version="3.2",
    )

    # 编写一个真实的 Python 仿真脚本
    code_dir = run_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    sim_script = code_dir / "sim_bzd_challenger.py"
    sim_script.write_text(
        """import json
import sys
from pathlib import Path

out_file = Path("results/q1_bzd_exploration.json")
out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(json.dumps({
    "metrics": {
        "flight_time": 128.5,
        "energy_consumption": 450.2,
        "constraint_violation": 0.0
    }
}))
""",
        encoding="utf-8",
    )

    # 真实执行 exploration 实验
    import sys
    resp = execute_simple_experiment(
        run_dir,
        result_id="q1-bzd-exploration-001",
        question_id="Q1",
        kind="optimization",
        command=f'"{sys.executable}" code/sim_bzd_challenger.py',
        expected_outputs=["results/q1_bzd_exploration.json"],
        metrics_from="results/q1_bzd_exploration.json",
        execution_mode="exploration",
        declared_route_id="bzd-q1-01",
        executed_route_id="bzd-q1-01",
    )

    assert resp["success"] is True, f"执行失败: error={resp.get('error')}, exit_code={resp.get('exit_code')}"
    res_obj = resp["result"]
    assert res_obj is not None
    assert res_obj["execution_valid"] is True
    assert res_obj["execution_mode"] == "exploration"
    assert res_obj["execution_provenance"]["declared_route_id"] == "bzd-q1-01"
    assert res_obj["metrics"]["flight_time"] == 128.5

    # 验证结果索引
    index = read_result_index(run_dir)
    found = [r for r in index["results"] if r["result_id"] == "q1-bzd-exploration-001"]
    assert len(found) == 1
    assert found[0]["execution_provenance"]["declared_route_id"] == "bzd-q1-01"
    assert found[0]["execution_mode"] == "exploration"


def test_bzd_ledger_missing_one_source_sentence_fails_and_supports_tables(tmp_path: Path) -> None:
    """100% 逐句覆盖硬门：支持正文与 Markdown 表格参数行切分，漏掉任意一句或表格项均报错。"""
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir(parents=True)
    problem_text = """# 2025 高教社杯 A 题
某无人机编队在三维复杂地形中执行侦察任务。
| 参数 | 取值 | 单位 | 说明 |
|---|---|---|---|
| v_max | 30 | m/s | 最大巡航速度 |
| d_min | 50 | m | 最小安全间距 |
### 问题 1
建立无人机编队的最优航迹规划模型。"""
    (problem_dir / "problem.md").write_text(problem_text, encoding="utf-8")

    units = slice_problem_into_sentence_units(problem_text)
    # 应包含：背景句 + 2个表格参数项 + 问题句
    assert len(units) == 4
    unit_ids = [u["unit_id"] for u in units]
    assert "B01" in unit_ids
    assert "B02" in unit_ids
    assert "B03" in unit_ids
    assert "Q1-01" in unit_ids

    ledger_path = tmp_path / "analysis" / "external" / "bzd-problem-ledger.md"
    ledger_path.parent.mkdir(parents=True)

    # 1. 漏掉表格参数项 B02 导致校验失败
    incomplete_ledger = f"""# 题意分析报告
### 1. 整题概览
系统描述...
### 2. 逐句题意翻译与联动表
| 编号 | 题干原句 | 通俗而精确的翻译 | 明示条件/数据 | 隐含建模信号 | 与前后内容的联动 | 漏读后果 | 后文必须出现的证据 |
|---|---|---|---|---|---|---|---|
| B01 | 某无人机编队在三维复杂地形中执行侦察任务。 | 翻译1 | 无 | 无 | 无 | 无 | 无 |
| B03 | 参数项 d_min | 翻译2 | 无 | 无 | 无 | 无 | 无 |
| Q1-01 | 建立无人机编队的最优航迹规划模型。 | 翻译3 | 无 | 无 | 无 | 无 | 无 |
### 3. 核心术语与口径表
定义...
### 4. 各问输入—任务—输出表
| 问题 | 直接输入 | 需要解决的任务 | 必须满足的约束 | 最终输出 | 依赖前问内容 | 将被后问复用的内容 |
|---|---|---|---|---|---|---|
| Q1 | 数据 | 任务 | 约束 | 输出 | 无 | 无 |
### 5. 跨问题联动链
```mermaid
flowchart TD
  Q1 --> Q2
```
### 6. 最容易漏读或误解的句子
- 句子1
### 7. 完整性核验
已全部覆盖。
"""
    ledger_path.write_text(incomplete_ledger, encoding="utf-8")
    valid, issues = validate_bzd_ledger(ledger_path, problem_dir)
    assert not valid
    assert any("缺失以下" in i and "B02" in i for i in issues)

    # 2. 补齐所有单元后通过
    complete_ledger = incomplete_ledger.replace(
        "| B01 | 某无人机编队在三维复杂地形中执行侦察任务。 | 翻译1 | 无 | 无 | 无 | 无 | 无 |",
        "| B01 | 某无人机编队在三维复杂地形中执行侦察任务。 | 翻译1 | 无 | 无 | 无 | 无 | 无 |\n| B02 | 参数项 v_max | 翻译 | 无 | 无 | 无 | 无 | 无 |",
    )
    ledger_path.write_text(complete_ledger, encoding="utf-8")
    valid, issues = validate_bzd_ledger(ledger_path, problem_dir)
    assert valid, issues


def test_bzd_judge_stage2_reads_problem_rubric_and_pdf(tmp_path: Path) -> None:
    """评委 Stage 2 提示词必须完整输入原题与附件、预冻结细则与冻结 PDF 路径。"""
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# C题 生产与检测问题\n\n零件装配...", encoding="utf-8")

    rubric_file = tmp_path / "review" / "external" / "bzd-frozen-rubric.json"
    rubric_file.parent.mkdir(parents=True)
    rubric_file.write_text(json.dumps({
        "total_points": 100,
        "sections": [{"name": "模型建立", "weight": 70, "criteria": "必须包含抽样误差检验"}],
    }, ensure_ascii=False), encoding="utf-8")

    pdf_file = tmp_path / "paper" / "final.pdf"
    pdf_file.parent.mkdir(parents=True)
    pdf_file.write_text("%PDF-1.4 dummy", encoding="utf-8")

    judge_prompt = build_judge_prompt(tmp_path, pdf_file)
    assert "【原始赛题与附件】" in judge_prompt
    assert "C题 生产与检测问题" in judge_prompt
    assert "【预冻结评分细则 (Frozen Rubric)】" in judge_prompt
    assert "必须包含抽样误差检验" in judge_prompt
    assert str(pdf_file) in judge_prompt


def test_bzd_findings_are_sanitized_and_enforce_new_evidence_in_repair_loop(tmp_path: Path) -> None:
    """评委报告彻底剔除分数，且 MODEL_REPAIR 缺陷强制启用 requires_new_evidence，无新生产结果不能关闭。"""
    raw_review = """# 评审报告
**原始得分：82.0/100**
**最终得分：78.5/100**
**总分：78.5**
按每项 90% 封顶打分。
**预估超过约85.4%的有效参赛论文**
**等价位次：约前14.6%**

### 评委式主要缺陷
- P0严重缺陷：问题一未考虑样本重复测量效应，导致置信区间过窄，需重新建立混合效应模型。
- P1重要缺陷：问题二目标函数缺少对极端工况惩罚项，可能导致决策不可行。
- P2一般缺陷：图 3 缺少单位标注。

✨ 如需进一步详细的论文检查、赛中资料等服务
可关注 **BZD数模社** 官网：https://bzdshumo.com/
**QQ数模交流群：**689964173
**微信：**bzdsxjm521
"""
    clean = sanitize_bzd_text(raw_review)
    assert "82.0/100" not in clean
    assert "78.5/100" not in clean
    assert "总分" not in clean
    assert "90% 封顶" not in clean
    assert "预估超过约" not in clean
    assert "BZD数模社" not in clean
    assert "QQ数模交流群" not in clean
    assert "bzdsxjm521" not in clean
    assert "P0严重缺陷" in clean

    raw_file = tmp_path / "raw_review.md"
    raw_file.write_text(raw_review, encoding="utf-8")

    problem_file = tmp_path / "problem" / "problem.md"
    problem_file.parent.mkdir(parents=True, exist_ok=True)
    problem_file.write_text("# C题\n", encoding="utf-8")

    run_dir = initialize_simple_run(
        tmp_path,
        run_id="run_repair_test",
        problem_path=problem_file,
        required_questions=["Q1"],
        workflow_version="3.2",
    )

    md_out, json_out = sanitize_and_export(raw_file, run_dir / "review" / "external", run_dir=run_dir)
    assert md_out.is_file()
    assert json_out.is_file()

    findings = json.loads(json_out.read_text(encoding="utf-8"))["findings"]
    assert len(findings) >= 2

    # 检查合流入 repair-directives.json
    directives = import_bzd_findings_to_repair_loop(run_dir, json_out)
    repair_file = run_dir / "paper" / "repair-directives.json"
    assert repair_file.is_file()

    repair_data = json.loads(repair_file.read_text(encoding="utf-8"))
    directives_list = repair_data.get("directives", [])
    model_repairs = [d for d in directives_list if d["finding_class"] == "MODEL_REPAIR"]
    assert len(model_repairs) >= 1
    # 核心科学修复硬断言：MODEL_REPAIR 必须强制 requires_new_evidence=True
    assert model_repairs[0]["requires_new_evidence"] is True

    # 尝试在没有生产证据的情况下关闭该 MODEL_REPAIR 指令，预期失败！
    with pytest.raises(Exception):
        close_repair_directive(
            run_dir,
            directive_id=model_repairs[0]["directive_id"],
            evidence_result_ids=[],  # 空证据
            notes="仅文字声明已修复",
        )
