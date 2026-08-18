"""BZD 外部评审报告清洗与缺陷提取工具。

功能：
1. 剔除营销推广与联系方式（BZD数模社官网、QQ群、微信等）；
2. 剔除主观位次预测与奖项插值（消除非客观幻觉）；
3. 修正 90% 评分天花板带来的偏差，区分“评委政策保留”与“真实论文缺陷”；
4. 提取结构化缺陷清单（P0/P1/P2、缺失任务、修改建议），生成合流 JSON。
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


def sanitize_bzd_text(raw_text: str) -> str:
    """清洗 BZD 报告文本，剔除广告、营销和主观位次预测。"""
    text = raw_text

    # 1. 剔除 HTML 广告卡片 / Markdown 推广块
    patterns_to_remove = [
        r"<aside\s+class=[\"']card service[\"'].*?</aside>",
        r"✨\s*如需进一步详细的论文检查.*?备用微信[^\n<]*",
        r"✨\s*如需.*?BZD数模社[^\n<]*",
        r"【?BZD数模社联系方式】?.*?(?=###|\Z)",
        r"\*\*QQ数模交流群[^\n<]*",
        r"\*\*资料通知群[^\n]*",
        r"\*\*微信（个性化定制）[^\n]*",
        r"备用微信[：:][^\n]*",
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

    # 清理多余空行
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
        if "不通过（硬性）" in text or "不合格" in text or "资格" in text and "未通过" in text:
            add_finding(text, "P0", "OBJECTIVE_REDESIGN" if "模型" in text else "WRITING_FIX")
        elif "普通格式问题" in text:
            add_finding(text, "P1", "WRITING_FIX")
        elif re.search(r"第[一二]优先级", text):
            add_finding(text, "P0" if "数据泄漏" in text or "删失" in text or "重叠" in text else "P1", "MODEL_REPAIR" if "模型" in text or "建模" in text else "WRITING_FIX")
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

        # 匹配 P0 / P1 / P2 标记或严重/重要缺陷
        if re.search(r"(P0|严重缺陷)", stripped, re.IGNORECASE):
            add_finding(stripped, "P0", "MODEL_REPAIR" if "模型" in stripped or "数据" in stripped else "WRITING_FIX")
        elif re.search(r"(P1|重要缺陷)", stripped, re.IGNORECASE):
            add_finding(stripped, "P1", "MODEL_REPAIR" if "模型" in stripped else "WRITING_FIX")
        elif re.search(r"(P2|一般缺陷)", stripped, re.IGNORECASE):
            add_finding(stripped, "P2", "WRITING_FIX")
        elif re.search(r"^[-*\d\.\s、]*(第[一二三四五]优先级|优先修改建议|[1-5][\.、])", stripped):
            clean_item = re.sub(r"^[-*\d\.\s、]+", "", stripped)
            add_finding(clean_item, "P1", "WRITING_FIX")

    return findings


def sanitize_and_export(raw_review_path: Path, output_dir: Path | None = None) -> tuple[Path, Path]:
    """读取原始报告，执行清洗并输出 sanitized markdown 与 findings json。"""
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
    findings_json.write_text(json.dumps({
        "schema_version": "1.0",
        "source": "bzd-review-paper",
        "sanitized_file": str(sanitized_md.name),
        "total_findings": len(findings),
        "findings": findings,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    return sanitized_md, findings_json


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗 BZD 评审报告并提取结构化缺陷")
    parser.add_argument("review_file", type=Path, help="原始评审报告路径 (.md 或 .html)")
    parser.add_argument("--out-dir", type=Path, default=None, help="清洗后文件输出目录")
    args = parser.parse_args()

    md_out, json_out = sanitize_and_export(args.review_file, args.out_dir)
    print("清洗完成:")
    print(f"  Sanitized Markdown: {md_out}")
    print(f"  Structured Findings ({json_out.stat().st_size} bytes): {json_out}")


if __name__ == "__main__":
    main()
