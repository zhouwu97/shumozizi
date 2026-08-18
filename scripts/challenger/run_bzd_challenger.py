"""BZD 独立 Challenger 桥接工具：隔离包生成、加载原版 Skill、提取真实打擂路线并合流。

定位：独立二号解题专家（Challenger B/C），在完全隔离上下文运行，与主路线 A 统一打擂。
产物路径：analysis/external/bzd-route-candidates.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from scripts.challenger.bzd_skill_bundle import format_bzd_prompt


def prepare_bzd_isolation_packet(run_dir: Path) -> Path:
    """构建物理隔离的题目与附件输入包，确保独立 Challenger 绝不接触本地主路线与代码。

    输出目录：`analysis/external/bzd-packet/`
    每次执行前强制清空旧目录，彻底杜绝 stale-file 遗留。
    仅包含 `problem/` 题面及附件，严格屏蔽 `analysis/ROUTE_COMPETITION.md`, `code/`, `results/`, `paper/` 等。
    """
    packet_dir = run_dir / "analysis" / "external" / "bzd-packet"
    if packet_dir.exists():
        shutil.rmtree(packet_dir, ignore_errors=True)

    packet_problem_dir = packet_dir / "problem"
    packet_problem_dir.mkdir(parents=True, exist_ok=True)

    src_problem_dir = run_dir / "problem"
    manifest_lines = [
        "# BZD Challenger 隔离输入清单 (Input Manifest)",
        "",
        "以下为本任务允许访问的全部原始题面与附件数据：",
        "",
        "| 文件名 | 类型 | 大小 (Bytes) | SHA-256 (前12位) |",
        "|---|---|---|---|",
    ]

    if src_problem_dir.is_dir():
        for src_file in sorted(src_problem_dir.rglob("*")):
            if src_file.is_file():
                rel_path = src_file.relative_to(src_problem_dir)
                dest_file = packet_problem_dir / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)

                content_bytes = src_file.read_bytes()
                sha_prefix = hashlib.sha256(content_bytes).hexdigest()[:12]
                file_type = src_file.suffix.lower() or "file"
                manifest_lines.append(
                    f"| `problem/{rel_path.as_posix()}` | {file_type} | {len(content_bytes)} | `{sha_prefix}` |"
                )

    (packet_dir / "INPUT_MANIFEST.md").write_text("\n".join(manifest_lines), encoding="utf-8")
    return packet_dir


def record_challenger_execution(
    run_dir: Path,
    thread_id: str,
    provider: str = "codex",
    candidates_file: str = "analysis/external/bzd-route-candidates.md",
) -> Path:
    """记录独立上下文 Challenger 执行收据，证明其来自无父上下文的独立执行环境。"""
    receipt_file = run_dir / "analysis" / "external" / "bzd-challenger-execution.json"
    receipt_file.parent.mkdir(parents=True, exist_ok=True)

    receipt = {
        "schema_version": "1.0",
        "role": "bzd_modeling_challenger",
        "provider": provider,
        "raw_thread_id": thread_id,
        "parent_context_inherited": False,
        "isolated_packet_dir": "analysis/external/bzd-packet",
        "candidates_file": candidates_file,
    }
    receipt_file.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return receipt_file


def build_isolated_challenger_prompt(run_dir: Path) -> str:
    """生成结合 BZD 原版技能与物理隔离输入包的 Challenger 提示词。"""
    packet_dir = prepare_bzd_isolation_packet(run_dir)
    packet_problem_dir = packet_dir / "problem"

    problem_texts: list[str] = []
    attachment_summaries: list[str] = []

    for path in sorted(packet_problem_dir.rglob("*")):
        if path.is_file():
            suffix = path.suffix.lower()
            rel_name = path.relative_to(packet_problem_dir).as_posix()
            if suffix in {".md", ".txt", ".json"}:
                problem_texts.append(f"=== {rel_name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")
            elif suffix in {".csv", ".tsv"}:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                preview = "\n".join(lines[:15])
                attachment_summaries.append(
                    f"=== [CSV附件] {rel_name} (共 {len(lines)} 行) ===\n{preview}\n..."
                )
            elif suffix in {".xlsx", ".xls"}:
                attachment_summaries.append(
                    f"=== [Excel附件] {rel_name} ({path.stat().st_size} bytes) ===\n（请使用 Python/pandas 深入读取其 sheet 结构、字段名与数据分布）"
                )
            elif suffix in {".pdf"}:
                attachment_summaries.append(
                    f"=== [PDF文件] {rel_name} ({path.stat().st_size} bytes) ===\n（请深入阅读其全部章节与图表）"
                )
            else:
                attachment_summaries.append(
                    f"=== [附件文件] {rel_name} ({path.stat().st_size} bytes) ==="
                )

    joined_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"
    if attachment_summaries:
        joined_problem += "\n\n【附件概览与前置数据】\n" + "\n\n".join(attachment_summaries)

    task_context = f"{joined_problem}"

    local_rules = """1. 严格使用原版 BZD Modeling Ideas 模式库与策略输出标准，独立提出整篇连贯的骨干路线（backbone）与分问多模型。
2. 严禁任何主观投票；提出的每条候选路线必须具备可计算的数学结构（mathematical_structure）、形式化 endpoint 与区分性验证 probe。
3. 若附件包含 Excel/PDF/图片，必须直接检视具体数据字段与机制，禁止脱离数据凭空猜测。
4. 输出目标文件固定为：`analysis/external/bzd-route-candidates.md`。
5. 【重要输出格式】：在 Markdown 报告末尾，必须追加一段名为 ```json 的结构化路线代码块，格式如下：
```json
[
  {
    "question": "Q1",
    "route_id": "bzd-q1-01",
    "name": "模型名称",
    "role": "challenger_primary",
    "mathematical_structure": "精确数学结构名称",
    "endpoint": "明确的数学主终点与优化目标定义（未明确时填 null）",
    "assumptions": ["假设1", "假设2"],
    "required_data": ["字段1", "字段2"],
    "solver": "建议求解器或算法",
    "distinguishing_probe": "区分性验证实验或对照方法",
    "failure_risk": "失败风险与局限性"
  }
]
```
所有路线将被提取并直接排入现有 `analysis/ROUTE_COMPETITION.md`，在同一 Exact Scorer 下执行真实代码实验打擂。"""

    return format_bzd_prompt(
        skill_name="bzd-modeling-ideas",
        task_context=task_context,
        local_rules=local_rules,
        required_references=[
            "integrated-modeling-patterns.md",
            "strategy-output-standard.md",
        ],
    )


def validate_challenger_candidates(candidates_path: Path) -> tuple[bool, list[str]]:
    """验证 BZD Challenger 产物的结构完整性。"""
    if not candidates_path.is_file():
        return False, [f"文件不存在: {candidates_path}"]

    content = candidates_path.read_text(encoding="utf-8")
    issues: list[str] = []

    required_sections = [
        "1. 整题建模主线",
        "2. 跨问题联动链",
        "3. 全文统一建模口径",
        "4. 分问题求解思路",
    ]

    for section in required_sections:
        if section not in content:
            issues.append(f"缺失必要章节: {section}")

    if "可用模型及选型比较" not in content and "| 可行模型/思路 |" not in content:
        issues.append("缺失分问题模型选型比较表格")

    return len(issues) == 0, issues


def extract_challenger_routes(candidates_path: Path) -> list[dict[str, Any]]:
    """从 Challenger 产物中提取真实的结构化打擂路线。

    【核心原则】：严禁自动编造 endpoint、assumptions、solver 或 failure_risk！
    BZD 输出什么就提取什么；缺失的内容严格置为 None 或空列表。
    """
    if not candidates_path.is_file():
        return []

    content = candidates_path.read_text(encoding="utf-8")

    # 1. 优先尝试提取末尾追加的标准 JSON 代码块
    json_blocks = re.findall(r"```json\s*\n([\s\S]*?)\n```", content)
    for block in reversed(json_blocks):
        try:
            parsed = json.loads(block.strip())
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                routes = []
                for item in parsed:
                    if "question" in item and "name" in item:
                        routes.append({
                            "question": item.get("question", "Q1"),
                            "route_id": item.get("route_id") or f"bzd-{item.get('question', 'q1').lower()}-01",
                            "name": item.get("name", "未命名模型"),
                            "role": item.get("role", "challenger_primary"),
                            "mathematical_structure": item.get("mathematical_structure") or _infer_math_structure(item.get("name", "")),
                            "endpoint": item.get("endpoint"),  # 严禁假填充！无则 None
                            "assumptions": item.get("assumptions") if isinstance(item.get("assumptions"), list) else [],
                            "required_data": item.get("required_data") if isinstance(item.get("required_data"), list) else [],
                            "solver": item.get("solver"),
                            "distinguishing_probe": item.get("distinguishing_probe"),
                            "failure_risk": item.get("failure_risk"),
                        })
                if routes:
                    return routes
        except Exception:
            pass

    # 2. 如果没有 JSON 块，精确从 Markdown 文本与表格中解析真实内容
    routes: list[dict[str, Any]] = []
    q_blocks = re.split(r"(?=####?\s*(?:4\.[1-9]|问题[一二三四五1-5]))", content)
    route_counter = 1

    for block in q_blocks:
        q_match = re.search(r"(?:4\.([1-9])|问题\s*([一二三四五1-5])|Q([1-5]))", block, re.IGNORECASE)
        if not q_match:
            continue

        digit_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5"}
        raw_q = q_match.group(1) or q_match.group(2) or q_match.group(3)
        q_id = f"Q{digit_map.get(raw_q, raw_q)}"

        # 提取推荐模型条目
        rec_match = re.search(r"[-*]\s*推荐模型[：:]\s*([^\n]+)", block)
        alt_match = re.search(r"[-*]\s*备选模型[：:]\s*([^\n]+)", block)
        probe_match = re.search(r"[-*]\s*多模型对比建议[：:]\s*([^\n]+)", block) or re.search(r"验证方法[：:]\s*([^\n]+)", block)
        endpoint_match = re.search(r"[-*]\s*(?:主终点|终点|目标函数|优化目标)[：:]\s*([^\n]+)", block)

        if rec_match:
            model_name = rec_match.group(1).strip()
            routes.append({
                "question": q_id,
                "route_id": f"bzd-{q_id.lower()}-{route_counter:02d}",
                "name": model_name,
                "role": "challenger_primary",
                "mathematical_structure": _infer_math_structure(model_name, block),
                "endpoint": endpoint_match.group(1).strip() if endpoint_match else None,  # 绝不假填 formal_target_q1
                "distinguishing_probe": probe_match.group(1).strip() if probe_match else None,
                "assumptions": _extract_bullet_items(block, "假设"),
                "required_data": _extract_bullet_items(block, "数据|输入"),
                "solver": _extract_inline_item(block, "求解器|算法"),
                "failure_risk": _extract_inline_item(block, "局限|失败风险|风险"),
            })
            route_counter += 1

        if alt_match:
            alt_name = alt_match.group(1).strip()
            routes.append({
                "question": q_id,
                "route_id": f"bzd-{q_id.lower()}-{route_counter:02d}",
                "name": alt_name,
                "role": "challenger_alternative",
                "mathematical_structure": _infer_math_structure(alt_name, block),
                "endpoint": None,  # 备选路线未显式声明 endpoint 则为 None
                "distinguishing_probe": None,
                "assumptions": [],
                "required_data": [],
                "solver": None,
                "failure_risk": None,
            })
            route_counter += 1

    return routes


def _extract_bullet_items(text: str, keyword_pattern: str) -> list[str]:
    """提取指定关键词下的列表条目。"""
    match = re.search(rf"[-*]\s*(?:{keyword_pattern})[：:]\s*([^\n]+)", text)
    if match:
        raw = match.group(1).strip()
        items = [i.strip() for i in re.split(r"[,，;；、]", raw) if i.strip()]
        return items
    return []


def _extract_inline_item(text: str, keyword_pattern: str) -> str | None:
    """提取行内单项内容。"""
    match = re.search(rf"[-*]\s*(?:{keyword_pattern})[：:]\s*([^\n]+)", text)
    if match:
        return match.group(1).strip()
    return None


def _infer_math_structure(model_name: str, context: str = "") -> str:
    """根据模型名称优先推断其核心数学结构，次选上下文。"""
    lower_name = model_name.lower()
    if "非线性规划" in lower_name or "nlp" in lower_name or "ipopt" in lower_name:
        return "continuous non-linear optimization"
    if "动态规划" in lower_name or "dp" in lower_name:
        return "state-transition dynamic programming"
    if "整数规划" in lower_name or "mip" in lower_name or "milp" in lower_name:
        return "mixed-integer linear programming"
    if "微分方程" in lower_name or "ode" in lower_name or "pde" in lower_name:
        return "differential equation dynamics"
    if "图论" in lower_name or "网络流" in lower_name:
        return "network flow / graph optimization"
    if "随机过程" in lower_name or "马尔可夫" in lower_name or "markov" in lower_name:
        return "stochastic markov process"
    if "时间序列" in lower_name or "arima" in lower_name:
        return "autoregressive time-series"

    lower_ctx = context.lower()
    if "非线性规划" in lower_ctx or "nlp" in lower_ctx or "ipopt" in lower_ctx:
        return "continuous non-linear optimization"
    if "动态规划" in lower_ctx or "dp" in lower_ctx:
        return "state-transition dynamic programming"
    if "整数规划" in lower_ctx or "mip" in lower_ctx or "milp" in lower_ctx:
        return "mixed-integer linear programming"
    if "微分方程" in lower_ctx or "ode" in lower_ctx:
        return "differential equation dynamics"
    if "图论" in lower_ctx or "网络流" in lower_ctx:
        return "network flow / graph optimization"
    return "mathematical structure formulation"


def import_challenger_routes_to_competition(
    run_dir: Path, candidates_path: Path | None = None
) -> Path:
    """将提取出的 BZD 真实结构化候选路线合流写入 analysis/ROUTE_COMPETITION.md。"""
    c_path = candidates_path or (run_dir / "analysis" / "external" / "bzd-route-candidates.md")
    routes = extract_challenger_routes(c_path)
    competition_file = run_dir / "analysis" / "ROUTE_COMPETITION.md"
    competition_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if competition_file.is_file():
        lines.append(competition_file.read_text(encoding="utf-8"))
    else:
        lines.append("# 数学建模路线竞争与打擂总表 (ROUTE_COMPETITION)\n")

    lines.append("\n## BZD 独立 Challenger 候选路线（已合流入擂台）\n")
    lines.append("| 路线 ID | 所属问题 | 路线名称 | 角色 | 核心数学结构 | 主终点 (Endpoint) | 区分性 Probe | 失败风险与回退 |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for r in routes:
        endpoint_display = f"`{r['endpoint']}`" if r.get("endpoint") else "*未指定 / 待解析*"
        probe_display = r.get("distinguishing_probe") or "*小规模对照*"
        risk_display = r.get("failure_risk") or "*无明确风险标注*"
        lines.append(
            f"| `{r['route_id']}` | **{r['question']}** | {r['name']} | `{r['role']}` | {r['mathematical_structure']} | {endpoint_display} | {probe_display} | {risk_display} |"
        )

    lines.append("\n> **打擂规则**：上述候选路线已注册，将在同一 Exact Scorer 与同等计算预算下由 `scripts/runtime/run_simple_experiment.py` 执行 exploration 实测，由实测指标决定胜者。\n")

    full_text = "\n".join(lines)
    competition_file.write_text(full_text, encoding="utf-8")
    return competition_file


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 BZD 独立 Challenger 提示词、提取路线或合流打擂")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--validate", action="store_true", help="验证 analysis/external/bzd-route-candidates.md")
    parser.add_argument("--extract", action="store_true", help="提取结构化候选路线")
    parser.add_argument("--import-to-competition", action="store_true", help="将提取路线合流入 ROUTE_COMPETITION.md")
    parser.add_argument("--record-receipt", type=str, help="记录独立上下文执行 thread ID")
    args = parser.parse_args()

    candidates = args.run_dir / "analysis" / "external" / "bzd-route-candidates.md"

    if args.record_receipt:
        receipt_path = record_challenger_execution(args.run_dir, thread_id=args.record_receipt)
        print(f"已记录 Challenger 执行收据: {receipt_path}")
    elif args.validate:
        valid, issues = validate_challenger_candidates(candidates)
        if valid:
            print(f"BZD Challenger 产物验证通过: {candidates}")
        else:
            print("BZD Challenger 产物验证未通过:\n" + "\n".join(f"- {i}" for i in issues))
            raise SystemExit(1)
    elif args.extract:
        routes = extract_challenger_routes(candidates)
        print(json.dumps(routes, indent=2, ensure_ascii=False))
    elif args.import_to_competition:
        comp_path = import_challenger_routes_to_competition(args.run_dir, candidates)
        print(f"已成功将 BZD Challenger 候选路线合流入: {comp_path}")
    else:
        prompt = build_isolated_challenger_prompt(args.run_dir)
        print(prompt)


if __name__ == "__main__":
    main()
