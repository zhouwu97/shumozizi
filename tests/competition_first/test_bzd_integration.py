"""验证 BZD 数学建模 Skills 的集成合规性、隔离打擂契约与清洗合流逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.challenger.run_bzd_challenger import (
    build_isolated_challenger_prompt,
    extract_challenger_routes,
    validate_challenger_candidates,
)
from scripts.challenger.run_bzd_translator import (
    build_translator_prompt,
    validate_bzd_ledger,
)
from scripts.review.sanitize_bzd_review import (
    extract_findings_from_review,
    sanitize_and_export,
    sanitize_bzd_text,
)
from scripts.review.show_bzd_judge_prompt import (
    build_judge_prompt,
    build_rubric_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_bzd_vendor_asset_structure_and_pinned_source() -> None:
    """vendor/bzd-math-modeling 必须固定 commit，具备 MIT 许可证并包含三项完整技能。"""
    vendor_root = REPO_ROOT / "vendor" / "bzd-math-modeling"
    assert vendor_root.is_dir()

    source_path = vendor_root / "SOURCE.json"
    assert source_path.is_file()
    source_meta = json.loads(source_path.read_text(encoding="utf-8"))

    assert source_meta["repository"] == "https://github.com/BZDmathclub/bzd-math-modeling-skills"
    assert len(source_meta["commit"]) == 40
    assert source_meta["license"] == "MIT"
    assert set(source_meta["imported_paths"]) == {
        "bzd-problem-translator",
        "bzd-modeling-ideas",
        "bzd-review-paper",
    }

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


def test_bzd_translator_prompt_and_validation(tmp_path: Path) -> None:
    """测试题意翻译提示词生成与 Ledger 完整性校验。"""
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025年高教社杯A题\n\n某无人机编队协同任务...", encoding="utf-8")

    prompt = build_translator_prompt(tmp_path)
    assert "BZD Problem Translator" in prompt
    assert "2025年高教社杯A题" in prompt
    assert "逐句题意翻译与联动表" in prompt
    assert "analysis/external/bzd-problem-ledger.md" in prompt

    # 测试 Ledger 校验器
    ledger_path = tmp_path / "analysis" / "external" / "bzd-problem-ledger.md"
    ledger_path.parent.mkdir(parents=True)

    # 缺失内容时未通过
    ledger_path.write_text("# 简易分析", encoding="utf-8")
    valid, issues = validate_bzd_ledger(ledger_path)
    assert not valid
    assert len(issues) > 0

    # 完整内容时通过
    complete_ledger = """# 题意分析报告
### 1. 整题概览
系统描述...
### 2. 逐句题意翻译与联动表
| 编号 | 题干原句 | 通俗而精确的翻译 | 明示条件/数据 | 隐含建模信号 | 与前后内容的联动 | 漏读后果 | 后文必须出现的证据 |
|---|---|---|---|---|---|---|---|
| B01 | 原句1 | 翻译1 | 无 | 无 | 无 | 无 | 无 |
### 3. 核心术语与口径表
定义...
### 4. 各问输入—任务—输出表
| 问题 | 直接输入 | 需要解决的任务 | 必须满足的约束 | 最终输出 | 依赖前问内容 | 将被后问复用的内容 |
|---|---|---|---|---|---|---|
| Q1 | 数据 | 任务 | 约束 | 输出 | 无 | Q2 |
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
    ledger_path.write_text(complete_ledger, encoding="utf-8")
    valid, issues = validate_bzd_ledger(ledger_path)
    assert valid, issues


def test_bzd_challenger_context_isolation_and_extraction(tmp_path: Path) -> None:
    """Challenger 提示词必须严格隔离本地路线、代码与结果，并可提取候选路线。"""
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# B题 复杂优化问题", encoding="utf-8")

    prompt = build_isolated_challenger_prompt(tmp_path)
    assert "BZD Modeling Ideas Challenger" in prompt
    assert "完全隔离" in prompt
    assert "analysis/external/bzd-route-candidates.md" in prompt
    # 确保没有泄露本地内部路线字段
    assert "BASELINE_FREEZE" not in prompt

    candidates_path = tmp_path / "analysis" / "external" / "bzd-route-candidates.md"
    candidates_path.parent.mkdir(parents=True)

    sample_candidates = """# 建模方案候选
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
#### 4.1.1 问题概述
Q1
#### 4.1.2 总体求解思路
思路1
#### 4.1.3 可用模型及选型比较
| 可行模型/思路 | 模型本质与核心变量 | 完整实现步骤 | 所需数据与假设 | 优点 | 局限与失败风险 | 验证方法 | 与前后问题的接口 | 适用场景 |
|---|---|---|---|---|---|---|---|---|
| 动态规划 | 状态转移 | 逆序求解 | 阶段无后效 | 精确 | 状态爆炸 | 解析对照 | 输出状态 | 离散 |
- 推荐模型：基于状态转移的时空动态规划模型
- 选用理由：无后效性
- 备选模型：连续非线性规划松弛求解
- 多模型对比建议：小规模下 DP vs NLP
#### 4.1.4 创新与改进方向
| 创新或改进方向 | 基础方案 | 具体改动与实现步骤 | 预期改进 | 新增工作量 | 验证指标与对照实验 | 风险及备用方案 | 影响的问题 |
"""
    candidates_path.write_text(sample_candidates, encoding="utf-8")
    valid, issues = validate_challenger_candidates(candidates_path)
    assert valid, issues

    routes = extract_challenger_routes(candidates_path)
    assert len(routes) == 2
    assert routes[0]["role"] == "challenger_primary"
    assert "动态规划" in routes[0]["model"]
    assert routes[1]["role"] == "challenger_alternative"
    assert "非线性规划" in routes[1]["model"]


def test_bzd_judge_rubric_and_sanitization(tmp_path: Path) -> None:
    """评委两阶段提示词生成与报告广告/位次清洗。"""
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# C题 生产与检测", encoding="utf-8")

    rubric_prompt = build_rubric_prompt(tmp_path)
    assert "BZD Review Judge - 阶段一" in prompt_check(rubric_prompt)
    assert "bzd-frozen-rubric.json" in rubric_prompt

    judge_prompt = build_judge_prompt(tmp_path)
    assert "BZD Review Judge - 阶段二" in judge_prompt
    assert "bzd-review.md" in judge_prompt

    # 测试文本清洗
    dirty_text = """# 评审报告
**原始得分：82.0/100**
**最终得分：78.5/100**
**预估超过约85.4%的有效参赛论文**
**等价位次：约前14.6%**
这里的位次是根据既定的2025国赛分数锚点插值估算，

### 评委式评价
- P0严重缺陷：问题一将孕妇多次检测按独立记录处理，存在数据泄漏。
- 1. 第一优先级：必须采用孕妇分组交叉验证并控制临床漏诊。

✨ 如需进一步详细的论文检查、赛中资料等服务
可关注 **BZD数模社** 官网：https://bzdshumo.com/
**QQ数模交流群（主群1）：**689964173
**微信（个性化定制）：**bzdsxjm521
备用微信：bzdsxjm520
"""
    clean_text = sanitize_bzd_text(dirty_text)
    assert "BZD数模社" not in clean_text
    assert "QQ数模交流群" not in clean_text
    assert "bzdsxjm521" not in clean_text
    assert "预估超过约" not in clean_text
    assert "等价位次" not in clean_text
    assert "2025国赛分数锚点插值" not in clean_text
    assert "P0严重缺陷" in clean_text

    findings = extract_findings_from_review(clean_text)
    assert len(findings) >= 2
    assert any(f["severity"] == "P0" for f in findings)
    assert any("数据泄漏" in f["description"] for f in findings)

    # 测试端到端导出
    raw_file = tmp_path / "raw_review.md"
    raw_file.write_text(dirty_text, encoding="utf-8")
    md_out, json_out = sanitize_and_export(raw_file, tmp_path / "review" / "external")

    assert md_out.is_file()
    assert json_out.is_file()
    json_data = json.loads(json_out.read_text(encoding="utf-8"))
    assert json_data["total_findings"] >= 2
    assert json_data["source"] == "bzd-review-paper"


def prompt_check(p: str) -> str:
    return p
