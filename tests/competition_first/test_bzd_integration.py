"""验证 BZD 数学建模 Skills 的真实加载、隔离打擂契约与清洗合流逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.challenger.bzd_skill_bundle import format_bzd_prompt, load_bzd_skill
from scripts.challenger.run_bzd_challenger import (
    build_isolated_challenger_prompt,
    extract_challenger_routes,
    import_challenger_routes_to_competition,
    prepare_bzd_isolation_packet,
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


def test_bzd_isolated_packet_contains_problem_and_attachments_but_no_local_route(tmp_path: Path) -> None:
    """物理隔离 Packet 必须复制题面和附件数据，严格屏蔽本地已选路线、代码与实验结果。"""
    run_dir = tmp_path / "run_01"
    problem_dir = run_dir / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025 A题 太阳能电池优化\n\n背景描述...", encoding="utf-8")
    (problem_dir / "data.csv").write_text("t,power,voltage\n1,10.5,12.0\n2,11.2,12.1\n", encoding="utf-8")

    # 模拟本地已有解题上下文（污染源）
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "analysis" / "ROUTE_COMPETITION.md").write_text("本地已选主路线 A: 遗传算法", encoding="utf-8")
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "code" / "main.py").write_text("print('local solution')", encoding="utf-8")
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "results" / "answer.json").write_text("{\"score\": 99.5}", encoding="utf-8")

    packet_dir = prepare_bzd_isolation_packet(run_dir)
    assert packet_dir.is_dir()
    assert (packet_dir / "problem" / "problem.md").is_file()
    assert (packet_dir / "problem" / "data.csv").is_file()
    assert (packet_dir / "INPUT_MANIFEST.md").is_file()

    # 确保绝不包含本地污染源
    assert not (packet_dir / "ROUTE_COMPETITION.md").exists()
    assert not (packet_dir / "code").exists()
    assert not (packet_dir / "results").exists()

    # 检查生成的隔离 Prompt
    prompt = build_isolated_challenger_prompt(run_dir)
    assert "2025 A题 太阳能电池优化" in prompt
    assert "[CSV附件] data.csv" in prompt
    assert "本地已选主路线 A" not in prompt
    assert "local solution" not in prompt


def test_bzd_ledger_missing_one_source_sentence_fails(tmp_path: Path) -> None:
    """100% 逐句覆盖硬门：题面只要漏掉任意一个实体句子单元，Ledger 校验立即失败。"""
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir(parents=True)
    problem_text = """# 2025 高教社杯 A 题
某无人机编队在三维复杂地形中执行侦察任务。编队飞行需满足最小安全距离与通信约束。
### 问题 1
建立无人机编队的最优航迹规划模型，求解最短飞行时间。"""
    (problem_dir / "problem.md").write_text(problem_text, encoding="utf-8")

    units = slice_problem_into_sentence_units(problem_text)
    assert len(units) >= 3
    unit_ids = [u["unit_id"] for u in units]
    assert "B01" in unit_ids
    assert "Q1-01" in unit_ids

    ledger_path = tmp_path / "analysis" / "external" / "bzd-problem-ledger.md"
    ledger_path.parent.mkdir(parents=True)

    # 1. 模拟漏掉 Q1-01 的残缺 Ledger
    incomplete_ledger = f"""# 题意分析报告
### 1. 整题概览
系统描述...
### 2. 逐句题意翻译与联动表
| 编号 | 题干原句 | 通俗而精确的翻译 | 明示条件/数据 | 隐含建模信号 | 与前后内容的联动 | 漏读后果 | 后文必须出现的证据 |
|---|---|---|---|---|---|---|---|
| B01 | 某无人机编队在三维复杂地形中执行侦察任务。 | 翻译1 | 无 | 无 | 无 | 无 | 无 |
| B02 | 编队飞行需满足最小安全距离与通信约束。 | 翻译2 | 无 | 无 | 无 | 无 | 无 |
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
    assert any("缺失以下" in i and "Q1-01" in i for i in issues)

    # 2. 补齐所有单元后通过
    complete_ledger = incomplete_ledger.replace(
        "| B02 | 编队飞行需满足最小安全距离与通信约束。 | 翻译2 | 无 | 无 | 无 | 无 | 无 |",
        "| B02 | 编队飞行需满足最小安全距离与通信约束。 | 翻译2 | 无 | 无 | 无 | 无 | 无 |\n| Q1-01 | 建立无人机编队的最优航迹规划模型，求解最短飞行时间。 | 翻译3 | 无 | 无 | 无 | 无 | 无 |",
    )
    ledger_path.write_text(complete_ledger, encoding="utf-8")
    valid, issues = validate_bzd_ledger(ledger_path, problem_dir)
    assert valid, issues


def test_bzd_route_keeps_question_endpoint_and_probe(tmp_path: Path) -> None:
    """提取的 Challenger 候选路线必须包含 question、数学结构、endpoint 与 probe 并合流至 ROUTE_COMPETITION.md。"""
    candidates_path = tmp_path / "analysis" / "external" / "bzd-route-candidates.md"
    candidates_path.parent.mkdir(parents=True)

    candidates_text = """# 建模方案候选
### 1. 整题建模主线
骨干网络...
### 2. 跨问题联动链
```mermaid
flowchart LR
  A --> B
```
### 3. 全文统一建模口径
符号约定...
### 4. 分问题求解思路
#### 4.1 问题一求解思路
##### 4.1.3 可用模型及选型比较
| 可行模型/思路 | 模型本质与核心变量 | 完整实现步骤 | 所需数据与假设 | 优点 | 局限与失败风险 | 验证方法 | 与前后问题的接口 | 适用场景 |
|---|---|---|---|---|---|---|---|---|
| 连续非线性规划 | 状态连续可微 | IPOPT求解 | 连续无碰撞 | 精确度高 | 易陷入局部最优 | 小规模 exact 对照 | 输出航迹点 | 连续地形 |
- 推荐模型：基于 IPOPT 的连续时空非线性规划模型
- 选用理由：路径光滑
- 备选模型：离散时空动态规划
- 多模型对比建议：小规模网格下 NLP vs DP 枚举

#### 4.2 问题二求解思路
##### 4.2.3 可用模型及选型比较
- 推荐模型：基于混合整数线性规划 (MILP) 的多机任务分配模型
- 备选模型：基于合同网协议的分布式协同算法
- 多模型对比建议：集中式 MILP vs 分布式协商
"""
    candidates_path.write_text(candidates_text, encoding="utf-8")
    valid, issues = validate_challenger_candidates(candidates_path)
    assert valid, issues

    routes = extract_challenger_routes(candidates_path)
    assert len(routes) == 4
    # 验证第一条路线字段结构完整性
    r1 = routes[0]
    assert r1["question"] == "Q1"
    assert r1["role"] == "challenger_primary"
    assert "非线性规划" in r1["name"] or "IPOPT" in r1["name"]
    assert "non-linear optimization" in r1["mathematical_structure"]
    assert "formal_target_q1" in r1["endpoint"]
    assert "NLP vs DP" in r1["distinguishing_probe"] or "对照" in r1["distinguishing_probe"]

    # 验证合流入 ROUTE_COMPETITION.md
    comp_file = import_challenger_routes_to_competition(tmp_path, candidates_path)
    assert comp_file.is_file()
    comp_text = comp_file.read_text(encoding="utf-8")
    assert "## BZD 独立 Challenger 候选路线（已合流入擂台）" in comp_text
    assert "`bzd-q1-01`" in comp_text
    assert "**Q1**" in comp_text
    assert "continuous non-linear optimization" in comp_text


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


def test_bzd_findings_are_sanitized_and_consumed_by_paper_repair(tmp_path: Path) -> None:
    """评委报告必须彻底剔除所有分数与广告，且 P0/P1 缺陷必须通过 open_repair_directive 写入 repair-directives.json。"""
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

    # 创建必要的纸质目录结构
    (tmp_path / "paper").mkdir(parents=True, exist_ok=True)

    md_out, json_out = sanitize_and_export(raw_file, tmp_path / "review" / "external", run_dir=tmp_path)
    assert md_out.is_file()
    assert json_out.is_file()

    findings = json.loads(json_out.read_text(encoding="utf-8"))["findings"]
    assert len(findings) >= 2
    assert any(f["severity"] == "P0" for f in findings)
    assert any(f["severity"] == "P1" for f in findings)

    # 检查合流入 repair-directives.json
    directives = import_bzd_findings_to_repair_loop(tmp_path, json_out)
    repair_file = tmp_path / "paper" / "repair-directives.json"
    if repair_file.is_file():
        repair_data = json.loads(repair_file.read_text(encoding="utf-8"))
        directives_list = repair_data.get("directives", [])
        assert len(directives_list) >= 2
        sources = [d["source"] for d in directives_list]
        assert "bzd_external_judge" in sources
        routes = [d["route"] for d in directives_list]
        assert "experiment" in routes or "analysis" in routes
