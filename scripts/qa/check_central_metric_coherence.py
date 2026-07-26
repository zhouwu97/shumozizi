"""跨章节核心数值自洽检查：同一核心量在全文不得出现无法由舍入解释的矛盾值。

与 ``check_numeric_consistency``（论文 ``@metric`` 标注 vs 结果索引）不同，本检查
针对**正文中散写、未打标记**的数值——正是外部评审暴露的“摘要/某问/某图厚度互相
打架”这类硬伤。判定分级（与设计一致）：

* FAIL —— 核心量别名邻域内出现的带单位数值，既不等于该量权威值（含合法舍入/单位
  换算），也不等于结果索引中任何已登记数值：判为伪造或过期的矛盾值。
* WARN —— 该数值虽不等于本量权威值，但等于索引中**另一个**已登记量：疑似口径混用
  （如在“最终厚度”句里引用了初估值），交由盲审判断，不阻断。
* PASS —— 合法舍入、单位换算、点估计与区间端点、不同 result_id 的不同阶段值。

只有 ``central=true`` 的账本条目参与 FAIL；账本缺失时整体降级为不阻断的告警，使既有
运行不因新增门禁而失败。检查只扫描正文散文（排除模板导言区、附录代码与参考文献）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.qa.metric_ledger import (  # noqa: E402
    known_values,
    read_ledger,
    resolve_ledger_value,
    validate_ledger,
)
from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.simple.results import read_result_index  # noqa: E402

# 报告落盘文件名主干；与既有 numeric-consistency 检查区分，避免覆盖。
REPORT_STEM = "central-metric-coherence"

# 长度单位换算（统一到米）。裸 m 易与词首字母混淆，故不支持，只认带前缀/LaTeX 的形式。
_LENGTH_FACTOR: dict[str, float] = {
    "nm": 1e-9,
    "um": 1e-6,
    "mm": 1e-3,
    "cm": 1e-2,
    "dm": 1e-1,
}
# 数字与单位之间的分隔：普通空白、LaTeX 细space（\, \; \: \! \ ）与不断行空格 ~。
# 论文里 ``8.11\,\mu\mathrm{m}`` 是常态，若不吞掉 \, 就永远识别不到单位。
_SEP = r"(?:\s|~|\\[,;:!\s])*"
# 单位识别：数字之后紧邻的单位记号（容忍 LaTeX 写法与中文单位）。键为归一化单位。
_UNIT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("um", re.compile(_SEP + r"(?:\\(?:mu|upmu)\s*(?:\\mathrm)?\s*\{?\s*m\s*\}?|[µμ]\s*m|um|微米)")),
    ("nm", re.compile(_SEP + r"(?:(?:\\mathrm\s*)?\{?\s*nm\s*\}?|纳米)")),
    ("mm", re.compile(_SEP + r"(?:(?:\\mathrm\s*)?\{?\s*mm\s*\}?|毫米)")),
    ("cm", re.compile(_SEP + r"(?:(?:\\mathrm\s*)?\{?\s*cm\s*\}?|厘米)")),
    ("dm", re.compile(_SEP + r"(?:(?:\\mathrm\s*)?\{?\s*dm\s*\}?|分米)")),
    ("%", re.compile(_SEP + r"(?:\\%|%|％)")),
]
_NUMBER = re.compile(r"(?<![0-9A-Za-z.])([0-9]+(?:\.[0-9]+)?)")
_WINDOW_PRE = 14
_WINDOW_POST = 64


def _strip_comments(text: str, is_typst: bool) -> str:
    """剥离行注释，避免注释里的数字被误当正文数值。"""
    if is_typst:
        return re.sub(r"(?<!:)//.*", "", text)
    return re.sub(r"(?<!\\)%.*", "", text)


def _body_text_files(run_dir: Path) -> list[tuple[str, str]]:
    """收集参与自洽检查的正文散文（排除导言区、附录代码与参考文献）。

    Args:
        run_dir: v3 运行目录。

    Returns:
        (文件名, 去注释后的正文文本) 列表。
    """
    paper = run_dir / "paper"
    out: list[tuple[str, str]] = []
    main = paper / "main.tex"
    is_typst = False
    if not main.is_file():
        main = paper / "main.typ"
        is_typst = True
    if main.is_file():
        text = main.read_text(encoding="utf-8", errors="ignore")
        # 只取正文：LaTeX 丢弃 \begin{document} 之前的导言区（字号/几何等配置数字）。
        if not is_typst:
            marker = text.find(r"\begin{document}")
            if marker != -1:
                text = text[marker:]
        out.append((main.name, _strip_comments(text, is_typst)))
    sections = paper / "sections"
    if sections.is_dir():
        suffix = "*.typ" if is_typst else "*.tex"
        for path in sorted(sections.glob(suffix)):
            lower = path.name.lower()
            if path.name.startswith("A_") or "appendix" in lower or lower.startswith("preamble"):
                continue  # 附录代码与导言片段不算正文数值
            if lower.startswith("references"):
                continue
            out.append(
                (path.name, _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), is_typst))
            )
    return out


def _unit_after(text: str, pos: int) -> str | None:
    """识别文本 pos 处紧邻的单位记号，返回归一化单位或 None。

    倒数单位（如 ``cm^{-1}`` 波数）虽含 ``cm`` 字样却非长度，必须排除，否则会把
    光谱波数当成长度值误比对。
    """
    for unit, pattern in _UNIT_PATTERNS:
        match = pattern.match(text, pos)
        if match and match.start() == pos:
            if unit in _LENGTH_FACTOR and re.match(r"[}\s]*\^", text[match.end():match.end() + 6]):
                return None  # cm^{-1}/µm^{-1} 等倒数单位，非长度量
            return unit
    return None


def _decimals(literal: str) -> int:
    """字面量的小数位数，用于推断该处显示精度对应的舍入容差。"""
    return len(literal.split(".")[1]) if "." in literal else 0


def _matches(stated: str, stated_unit: str | None, expected: float, ledger_unit: str | None) -> bool:
    """带单位换算与显示精度容差地判断 stated 是否等于 expected。

    Args:
        stated: 正文中的数字字面量。
        stated_unit: 该数字紧邻的归一化单位（可能为 None）。
        expected: 账本指向的权威值（以 ledger_unit 计）。
        ledger_unit: 权威值单位。

    Returns:
        在合法舍入（及必要的单位换算）下是否一致。
    """
    value = float(stated)
    tol = 0.5 * 10 ** (-_decimals(stated)) + 1e-9
    if ledger_unit in _LENGTH_FACTOR and stated_unit in _LENGTH_FACTOR:
        scale = _LENGTH_FACTOR[stated_unit] / _LENGTH_FACTOR[ledger_unit]
        value *= scale
        tol *= scale
    return abs(value - expected) <= tol


def _requires_unit(ledger_unit: str | None) -> bool:
    """带明确单位的核心量，要求正文数字也带单位才算指代它（收紧误报）。"""
    return ledger_unit in _LENGTH_FACTOR or ledger_unit == "%"


def _unit_compatible(stated_unit: str | None, ledger_unit: str | None) -> bool:
    """正文数字的单位是否与核心量单位同量纲。

    长度量只认长度单位、百分比只认百分比；否则该数字与本量无关（如 μm 量旁的
    ``95\\%``），必须排除，否则会把无关数字误判为矛盾。无量纲账本不设限制。
    """
    if ledger_unit in _LENGTH_FACTOR:
        return stated_unit in _LENGTH_FACTOR
    if ledger_unit == "%":
        return stated_unit == "%"
    return True


def check_central_metric_coherence(run_dir: Path) -> dict[str, Any]:
    """检查核心量在全文的数值自洽。

    Args:
        run_dir: v3 运行目录。

    Returns:
        含 ``success`` 的可复核报告；账本缺失时 ``skipped=True`` 且不阻断。
    """
    ledger = read_ledger(run_dir)
    if ledger is None:
        return {
            "success": True,
            "skipped": True,
            "reason": "未提供 paper/generated/metric_ledger.json，核心数值自洽门禁未启用",
            "contradictions": [],
            "scope_warnings": [],
            "unstated_central": [],
        }
    errors = validate_ledger(ledger)
    if errors:
        return {"success": False, "skipped": False, "ledger_errors": errors,
                "contradictions": [], "scope_warnings": [], "unstated_central": []}

    try:
        read_result_index(run_dir)
        known = known_values(run_dir)
        current = {
            result["result_id"]: {
                key: float(val)
                for key, val in result["metrics"].items()
                if isinstance(val, (int, float)) and not isinstance(val, bool)
            }
            for result in read_result_index(run_dir)["results"]
            if result["status"] == "current"
        }
    except (ContractError, OSError) as exc:
        return {"success": False, "skipped": False, "index_error": str(exc),
                "contradictions": [], "scope_warnings": [], "unstated_central": []}

    body = _body_text_files(run_dir)
    contradictions: list[dict[str, Any]] = []
    scope_warnings: list[dict[str, Any]] = []
    unstated_central: list[dict[str, Any]] = []
    metrics_checked: list[str] = []

    for entry in ledger["metrics"]:
        expected = resolve_ledger_value(current, entry["source_result_id"], entry["source_metric"])
        if expected is None:
            # 账本指向的权威值不在 current 结果中：登记为账本错误（阻断，避免空指针漏检）。
            contradictions.append(
                {
                    "metric_id": entry["metric_id"],
                    "reason": "账本指向的 source_result_id.source_metric 不是 current 结果中的数值",
                    "source": f"{entry['source_result_id']}.{entry['source_metric']}",
                }
            )
            continue
        ledger_unit = entry.get("unit")
        central = bool(entry["central"])
        metrics_checked.append(entry["metric_id"])
        require_unit = _requires_unit(ledger_unit)
        stated_ok = False
        seen_pos: set[tuple[str, int]] = set()  # 重叠别名指向同一处数字时去重（如“外延层厚度”含“厚度”）

        for filename, text in body:
            for alias in entry["aliases"]:
                start = 0
                while True:
                    idx = text.find(alias, start)
                    if idx == -1:
                        break
                    start = idx + len(alias)
                    lo = max(0, idx - _WINDOW_PRE)
                    hi = min(len(text), idx + len(alias) + _WINDOW_POST)
                    window = text[lo:hi]
                    for number in _NUMBER.finditer(window):
                        literal = number.group(1)
                        unit = _unit_after(window, number.end())
                        if require_unit and not _unit_compatible(unit, ledger_unit):
                            continue  # 单位缺失或不同量纲，不视为对该量的陈述
                        abs_pos = lo + number.start()
                        if (filename, abs_pos) in seen_pos:
                            continue  # 同一处数字已由另一别名处理，勿重复计入
                        seen_pos.add((filename, abs_pos))
                        if _matches(literal, unit, expected, ledger_unit):
                            stated_ok = True
                            continue
                        # 不等于本量权威值：是等于“别的已登记量”（口径混用，WARN），
                        # 还是谁都不等于（伪造/过期，FAIL）。
                        other = next(
                            (name for value, name in known if _matches(literal, unit, value, ledger_unit)),
                            None,
                        )
                        snippet = re.sub(r"\s+", " ", window).strip()
                        record = {
                            "metric_id": entry["metric_id"],
                            "file": filename,
                            "alias": alias,
                            "stated": literal,
                            "unit": unit,
                            "expected": round(expected, 6),
                            "ledger_unit": ledger_unit,
                            "snippet": snippet,
                        }
                        if other is not None:
                            scope_warnings.append({**record, "matches_other": other})
                        elif central:
                            contradictions.append(record)
                        else:
                            scope_warnings.append({**record, "matches_other": None})

        if central and require_unit and not stated_ok:
            unstated_central.append(
                {
                    "metric_id": entry["metric_id"],
                    "expected": round(expected, 6),
                    "unit": ledger_unit,
                    "reason": "核心量的权威值未在任一别名邻域内清晰陈述",
                }
            )

    return {
        "success": not contradictions,
        "skipped": False,
        "metrics_checked": sorted(metrics_checked),
        "contradictions": contradictions,
        "scope_warnings": scope_warnings,
        "unstated_central": unstated_central,
        "warnings": [
            *(f"疑似口径混用：{item['metric_id']} 处出现 {item['stated']}（等于 {item.get('matches_other')}）"
              for item in scope_warnings if item.get("matches_other")),
            *(f"核心量未清晰陈述：{item['metric_id']}（期望 {item['expected']}{item['unit'] or ''}）"
              for item in unstated_central),
        ],
    }


def _render_markdown(run_dir: Path, report: dict[str, Any]) -> str:
    """把检查结果渲染为人类可读的核对表。"""
    lines = ["# 核心数值一致性检查", "", f"- 运行：{run_dir.name}"]
    if report.get("skipped"):
        lines += ["- 状态：未启用（缺 paper/generated/metric_ledger.json）", ""]
        return "\n".join(lines) + "\n"
    lines += [
        f"- 状态：{'PASS' if report['success'] else 'FAIL'}",
        f"- 参与核心量：{len(report.get('metrics_checked', []))}",
        "",
    ]
    if report.get("ledger_errors"):
        lines += ["## 账本结构错误", "", *[f"- {msg}" for msg in report["ledger_errors"]], ""]
    if report["contradictions"]:
        lines += ["## FAIL：矛盾/伪造的核心值", "",
                  "| 核心量 | 文件 | 数值 | 期望 | 片段 |", "|---|---|---:|---:|---|"]
        for item in report["contradictions"]:
            if "snippet" in item:
                lines.append(
                    f"| {item['metric_id']} | {item['file']} | {item['stated']}{item['unit'] or ''} "
                    f"| {item['expected']}{item['ledger_unit'] or ''} | {item['snippet'][:60]} |"
                )
            else:
                lines.append(f"| {item['metric_id']} | 账本 | — | — | {item.get('reason', '')} |")
        lines.append("")
    if report["scope_warnings"]:
        lines += ["## WARN：疑似口径混用（不阻断）", ""]
        for item in report["scope_warnings"]:
            other = item.get("matches_other") or "无匹配"
            lines.append(
                f"- {item['metric_id']} @ {item['file']}：{item['stated']}{item['unit'] or ''}"
                f"（等于 {other}）… {item['snippet'][:60]}"
            )
        lines.append("")
    if report["unstated_central"]:
        lines += ["## WARN：核心量权威值未清晰陈述", ""]
        for item in report["unstated_central"]:
            lines.append(f"- {item['metric_id']}：期望 {item['expected']}{item['unit'] or ''}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_reports(run_dir: Path, report: dict[str, Any]) -> None:
    """把检查结果落盘为 ``qa/central-metric-coherence.{json,md}``（人工复核用）。

    与既有 ``numeric-consistency`` 检查（``@metric`` 标注复核）区分命名，避免文件互相覆盖。

    Args:
        run_dir: v3 运行目录。
        report: :func:`check_central_metric_coherence` 的返回值。
    """
    qa_dir = run_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / f"{REPORT_STEM}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (qa_dir / f"{REPORT_STEM}.md").write_text(
        _render_markdown(run_dir, report), encoding="utf-8"
    )


def main() -> int:
    """命令行入口：检查并可选写出 ``qa/central-metric-coherence.{json,md}``。

    Returns:
        通过为 0，存在矛盾为 1。
    """
    parser = argparse.ArgumentParser(description="核心数值跨章节自洽检查")
    parser.add_argument("run_dir")
    parser.add_argument(
        "--write-report", action="store_true", help="写出 qa/central-metric-coherence.{json,md}"
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    report = check_central_metric_coherence(run_dir)
    if args.write_report:
        write_reports(run_dir, report)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
