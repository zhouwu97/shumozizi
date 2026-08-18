"""BZD 外部评审报告清洗、缺陷提取与修论文台账合流工具。

功能：
1. 剔除营销推广与联系方式（BZD数模社官网、QQ群、微信等）；
2. 彻底剔除所有数值打分、百分位位次预测、奖项估算与 90% 天花板保留说明；
3. 提取结构化缺陷清单（P0/P1/P2、缺失任务、修改建议），生成合流 JSON；
4. 将 P0/P1 缺陷通过 `open_repair_directive` 实质合流写入 `paper/repair-directives.json`。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from shumozizi.paper.repair_loop import open_repair_directive
except ImportError:
    open_repair_directive = None  # type: ignore[assignment]


def sanitize_bzd_text(raw_text: str) -> str:
    """清洗 BZD 报告文本，剔除广告、营销、数值分数、位次预测与 90% 天花板政策说明。"""
    text = raw_text

    # 1. 剔除 HTML 广告卡片 / Markdown 推广块
    patterns_to_remove = [
        r"<aside\s+class=[\"']card service[\"'].*?</aside>",
        r"✨\s*如需进一步详细的论文检查.*?备用微信[^\n<]*",
        r"✨\s*如需.*?BZD数模社[^\n<]*",
        r"【?BZD数模社联系方式】?.*?(?=###|\Z)",
        r"[\*\-]?\s*QQ[\s\S]*?(?:交流群|通知群)[^\n<]*",
        r"[\*\-]?\s*(?:备用)?微信(?:（[^）]+）)?[：:\s\*]+[a-zA-Z0-9_\-]+[^\n<]*",
        r"可关注\s*\*\*BZD数模社\*\*[^\n]*",
        r"https?://bzdshumo\.com[^\s\)\"<]*",
        r"<p\s+class=[\"']footer[\"']>BZD-review-paper[^\n<]*</p>",
    ]
    for pattern in patterns_to_remove:
        text = re.sub(pattern, "", text, flags=re.DOTALL | re.IGNORECASE)

    # 2. 剔除位次预测与奖项估算语句
    ranking_patterns = [
        r"[\*\-]?\s*预估超过约\s*[\d\.]+\s*%\s*的有效参赛论文[^\n<]*",
        r"[\*\-]?\s*等价位次[：:]\s*约前\s*[\d\.]+\s*%[^\n<]*",
        r"这里的位次是根据既定的\d+国赛分数锚点插值估算[^\n<]*",
        r"这里的位次按小型竞赛[^\n<]*",
    ]
    for pattern in ranking_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 3. 彻底剔除所有数值打分及 90% 天花板政策说明
    score_and_ceiling_patterns = [
        r"[\*\-]?\s*原始得分[：:\s\*]+[\d\.]+\s*/\s*100[^\n<]*",
        r"[\*\-]?\s*最终得分[：:\s\*]+[\d\.]+\s*/\s*100[^\n<]*",
        r"[\*\-]?\s*(?:总分|评分|得分)[：:\s\*]+[\d\.]+(?:/\d+)?[^\n<]*",
        r"按每项\s*90%\s*封顶[^\n<]*",
        r"每一评分项最高只能拿权重的\s*90%[^\n<]*",
        r"评委满分保留[^\n<]*",
    ]
    for pattern in score_and_ceiling_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 4. 清理由于正则剔除留下的纯星号/横线空行
    text = re.sub(r"^\s*[\*\-]+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def strip_html_tags(text: str) -> str:
    """去除 HTML 标签并还原实体字符。"""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = html.unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


def extract_findings_from_review(clean_text: str) -> list[dict[str, Any]]:
    """从清洗后的评审报告（HTML 或 Markdown）中提取结构化缺陷清单。"""
    findings: list[dict[str, Any]] = []
    finding_idx = 1
    seen_texts: set[str] = set()

    def add_finding(desc: str, severity: str, action_type: str) -> None:
        nonlocal finding_idx
        desc_clean = desc.strip()
        if not desc_clean or desc_clean in seen_texts or len(desc_clean) < 8:
            return
        seen_texts.add(desc_clean)
        findings.append({
            "finding_id": f"BZD-REV-{finding_idx:03d}",
            "severity": severity,
            "description": desc_clean,
            "source": "bzd_external_judge",
            "action_type": action_type,
            "status": "OPEN",
        })
        finding_idx += 1

    # 1. 针对 HTML 提取 <li> 标签
    li_matches = re.findall(r"<li[^>]*>(.*?)</li>", clean_text, flags=re.DOTALL)
    for raw_li in li_matches:
        text = strip_html_tags(raw_li)
        if "不通过（硬性）" in text or "不合格" in text or ("资格" in text and "未通过" in text):
            add_finding(text, "P0", "OBJECTIVE_REDESIGN" if "目标" in text or "口径" in text else "MODEL_REPAIR")
        elif "普通格式问题" in text:
            add_finding(text, "P2", "WRITING_FIX")
        elif re.search(r"第[一二]优先级", text):
            add_finding(
                text,
                "P0" if "数据泄漏" in text or "删失" in text or "重叠" in text else "P1",
                "MODEL_REPAIR" if "模型" in text or "建模" in text else "WRITING_FIX",
            )
        elif re.search(r"第[三四五]优先级", text):
            add_finding(text, "P1", "MODEL_REPAIR" if "模型" in text or "权重" in text else "WRITING_FIX")
        elif re.search(r"问题[一二三四1-4]", text) and not text.startswith("问题一：分析"):
            add_finding(text, "P1", "MODEL_REPAIR")

    # 2. 针对 HTML 表格中包含缺陷的单元格提取
    tr_matches = re.findall(r"<tr>(.*?)</tr>", clean_text, flags=re.DOTALL)
    for raw_tr in tr_matches:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", raw_tr, flags=re.DOTALL)
        if len(tds) >= 6:
            defect_text = strip_html_tags(tds[-1])
            module_name = strip_html_tags(tds[0])
            if len(defect_text) > 15 and "无" not in defect_text:
                add_finding(f"[{module_name}] {defect_text}", "P1", "MODEL_REPAIR")

    # 3. 针对 Markdown 行提取
    lines = clean_text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("<"):
            continue

        if re.search(r"(P0|严重缺陷)", stripped, re.IGNORECASE):
            add_finding(
                stripped,
                "P0",
                "OBJECTIVE_REDESIGN" if "目标" in stripped or "题意" in stripped else "MODEL_REPAIR",
            )
        elif re.search(r"(P1|重要缺陷)", stripped, re.IGNORECASE):
            add_finding(stripped, "P1", "MODEL_REPAIR" if "模型" in stripped or "计算" in stripped else "WRITING_FIX")
        elif re.search(r"(P2|一般缺陷)", stripped, re.IGNORECASE):
            add_finding(stripped, "P2", "WRITING_FIX")
        elif re.search(r"^[-*\d\.\s、]*(第[一二三四五]优先级|优先修改建议|[1-5][\.、])", stripped):
            clean_item = re.sub(r"^[-*\d\.\s、]+", "", stripped)
            add_finding(clean_item, "P1", "WRITING_FIX")

    return findings


def import_bzd_findings_to_repair_loop(
    run_dir: Path, findings_path: Path | None = None
) -> list[dict[str, Any]]:
    """将 BZD 外部评委发现的 P0/P1 结构化缺陷合流写入 `paper/repair-directives.json`。"""
    f_path = findings_path or (run_dir / "review" / "external" / "bzd-review-findings.json")
    if not f_path.is_file():
        return []

    data = json.loads(f_path.read_text(encoding="utf-8"))
    findings = data.get("findings", [])
    registered: list[dict[str, Any]] = []

    if open_repair_directive is None:
        return []

    for f in findings:
        severity = f.get("severity", "P2")
        if severity not in {"P0", "P1"}:
            continue

        action_type = f.get("action_type", "WRITING_FIX")
        if action_type == "OBJECTIVE_REDESIGN":
            route = "analysis"
            owner_stage = "analysis"
        elif action_type == "MODEL_REPAIR":
            route = "experiment"
            owner_stage = "experiment"
        elif action_type == "VISUAL_FIX":
            route = "visual"
            owner_stage = "visual"
        else:
            route = "author"
            owner_stage = "author"

        requires_new_evidence = action_type in {"MODEL_REPAIR", "OBJECTIVE_REDESIGN"}

        try:
            directive = open_repair_directive(
                run_dir,
                directive_id=f["finding_id"],
                source="bzd_external_judge",
                finding_class=action_type,
                route=route,
                owner_stage=owner_stage,
                repair_action=f["description"],
                acceptance_test=f"响应 BZD 外部评委缺陷并完成对应阶段复验: {f['finding_id']}",
                requires_new_evidence=requires_new_evidence,
            )
            registered.append(directive)
        except Exception:
            # 已存在或其他非阻断情况
            pass

    return registered


def sanitize_and_export(
    raw_review_path: Path,
    output_dir: Path | None = None,
    run_dir: Path | None = None,
) -> tuple[Path, Path]:
    """读取原始报告，执行清洗、导出并在提供 run_dir 时自动合流入 repair_loop。"""
    if not raw_review_path.is_file():
        raise FileNotFoundError(f"评审报告不存在: {raw_review_path}")

    out_dir = output_dir or raw_review_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_text = raw_review_path.read_text(encoding="utf-8", errors="ignore")
    clean_text = sanitize_bzd_text(raw_text)
    findings = extract_findings_from_review(clean_text)

    sanitized_md = out_dir / "bzd-review-sanitized.md"
    sanitized_md.write_text(clean_text, encoding="utf-8")

    findings_json = out_dir / "bzd-review-findings.json"
    findings_json.write_text(
        json.dumps({
            "schema_version": "1.0",
            "source": "bzd-review-paper",
            "sanitized_file": str(sanitized_md.name),
            "total_findings": len(findings),
            "findings": findings,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    target_run_dir = run_dir
    if target_run_dir is None:
        possible = raw_review_path.resolve().parents[2]
        if (possible / "paper").is_dir() or (possible / "analysis").is_dir():
            target_run_dir = possible

    if target_run_dir:
        import_bzd_findings_to_repair_loop(target_run_dir, findings_json)

    return sanitized_md, findings_json


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗 BZD 评审报告并合流进入修论文台账")
    parser.add_argument("review_file", type=Path, help="原始评审报告路径 (.md 或 .html)")
    parser.add_argument("--out-dir", type=Path, default=None, help="清洗后文件输出目录")
    parser.add_argument("--run-dir", type=Path, default=None, help="运行目录（用于合流进入 repair-directives）")
    args = parser.parse_args()

    md_out, json_out = sanitize_and_export(args.review_file, args.out_dir, args.run_dir)
    print("清洗与合流完成:")
    print(f"  Sanitized Markdown: {md_out}")
    print(f"  Structured Findings: {json_out}")


if __name__ == "__main__":
    main()
