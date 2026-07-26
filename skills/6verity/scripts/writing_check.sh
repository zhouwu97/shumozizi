#!/usr/bin/env bash
set -u

usage() {
  cat <<'EOF'
Usage:
  writing_check.sh [paper-dir]
  writing_check.sh --paper-dir DIR [options]

Options:
  --root-dir DIR          Project root. Defaults to the parent of paper-dir.
  --main FILE            Paper entry file. Supports both Typst (main.typ) and LaTeX (main.tex). Defaults to <paper-dir>/main.typ, then main.tex.
  --sections-dir DIR     Section directory. Defaults to <paper-dir>/sections when it exists.
  --references FILE      Reference file. Defaults to <paper-dir>/references.typ when it exists.
  --figures-dir DIR      Figure directory. Defaults to <root-dir>/figures when it exists.
  --results-file FILE    Result summary file. Defaults to <root-dir>/reports/RESULTS_REPORT.md when it exists.
  --problem-analysis FILE
                          Problem analysis file, used only for soft consistency checks.
  --all-results FILE     Aggregated JSON result file. Defaults to <figures-dir>/all_results.json.
  --internal-term TEXT   Extra internal workflow term to reject in paper body. Repeatable.
  --no-internal-check    Skip internal workflow filename leak check.
  -h, --help             Show this help.

The script intentionally accepts paths from the caller. Defaults are convenience
fallbacks only; the verification skill should infer the project layout and pass
the actual files it wants checked.
EOF
}

PAPER_DIR="${PAPER_DIR:-}"
ROOT_DIR="${ROOT_DIR:-}"
MAIN_FILE="${MAIN_FILE:-}"
SECTIONS_DIR="${SECTIONS_DIR:-}"
REFERENCES_FILE="${REFERENCES_FILE:-}"
FIGURES_DIR="${FIGURES_DIR:-}"
RESULTS_FILE="${RESULTS_FILE:-}"
PROBLEM_ANALYSIS_FILE="${PROBLEM_ANALYSIS_FILE:-}"
ALL_RESULTS_FILE="${ALL_RESULTS_FILE:-}"
NO_INTERNAL_CHECK="${NO_INTERNAL_CHECK:-0}"
EXTRA_INTERNAL_TERMS=()
POSITIONAL=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --paper-dir)
      PAPER_DIR="${2:-}"
      shift 2
      ;;
    --root-dir)
      ROOT_DIR="${2:-}"
      shift 2
      ;;
    --main)
      MAIN_FILE="${2:-}"
      shift 2
      ;;
    --sections-dir)
      SECTIONS_DIR="${2:-}"
      shift 2
      ;;
    --references)
      REFERENCES_FILE="${2:-}"
      shift 2
      ;;
    --figures-dir)
      FIGURES_DIR="${2:-}"
      shift 2
      ;;
    --results-file)
      RESULTS_FILE="${2:-}"
      shift 2
      ;;
    --problem-analysis)
      PROBLEM_ANALYSIS_FILE="${2:-}"
      shift 2
      ;;
    --all-results)
      ALL_RESULTS_FILE="${2:-}"
      shift 2
      ;;
    --internal-term)
      EXTRA_INTERNAL_TERMS+=("${2:-}")
      shift 2
      ;;
    --no-internal-check)
      NO_INTERNAL_CHECK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        POSITIONAL+=("$1")
        shift
      done
      ;;
    -*)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [ -z "$PAPER_DIR" ] && [ "${#POSITIONAL[@]}" -gt 0 ]; then
  PAPER_DIR="${POSITIONAL[0]}"
fi

if [ -z "$PAPER_DIR" ]; then
  if [ -f "main.typ" ] || [ -f "main.tex" ]; then
    PAPER_DIR="."
  else
    CANDIDATE="$(find . -maxdepth 3 -type f \( -name main.typ -o -name main.tex \) -print 2>/dev/null | head -n 1 || true)"
    if [ -n "$CANDIDATE" ]; then
      PAPER_DIR="$(dirname "$CANDIDATE")"
    else
      PAPER_DIR="paper"
    fi
  fi
fi

if [ -z "$ROOT_DIR" ]; then
  if [ "$PAPER_DIR" = "." ]; then
    ROOT_DIR="."
  else
    ROOT_DIR="$(cd "$PAPER_DIR/.." 2>/dev/null && pwd || dirname "$PAPER_DIR")"
  fi
fi

if [ -z "$MAIN_FILE" ]; then
  if [ -f "$PAPER_DIR/main.typ" ]; then
    MAIN_FILE="$PAPER_DIR/main.typ"
  elif [ -f "$PAPER_DIR/main.tex" ]; then
    MAIN_FILE="$PAPER_DIR/main.tex"
  fi
fi

if [ -z "$SECTIONS_DIR" ] && [ -d "$PAPER_DIR/sections" ]; then
  SECTIONS_DIR="$PAPER_DIR/sections"
fi

if [ -z "$REFERENCES_FILE" ]; then
  if [ -f "$PAPER_DIR/references.typ" ]; then
    REFERENCES_FILE="$PAPER_DIR/references.typ"
  elif [ -f "$PAPER_DIR/references.tex" ]; then
    REFERENCES_FILE="$PAPER_DIR/references.tex"
  fi
fi

if [ -z "$FIGURES_DIR" ] && [ -d "$ROOT_DIR/figures" ]; then
  FIGURES_DIR="$ROOT_DIR/figures"
fi

if [ -z "$RESULTS_FILE" ]; then
  if [ -f "$ROOT_DIR/reports/RESULTS_REPORT.md" ]; then
    RESULTS_FILE="$ROOT_DIR/reports/RESULTS_REPORT.md"
  elif [ -f "$ROOT_DIR/RESULTS_REPORT.md" ]; then
    RESULTS_FILE="$ROOT_DIR/RESULTS_REPORT.md"
  elif [ -f "$ROOT_DIR/RESULTS_REPORT" ]; then
    RESULTS_FILE="$ROOT_DIR/RESULTS_REPORT"
  fi
fi

if [ -z "$PROBLEM_ANALYSIS_FILE" ] && [ -f "$ROOT_DIR/PROBLEM_ANALYSIS.md" ]; then
  PROBLEM_ANALYSIS_FILE="$ROOT_DIR/PROBLEM_ANALYSIS.md"
fi

if [ -z "$ALL_RESULTS_FILE" ] && [ -n "$FIGURES_DIR" ] && [ -f "$FIGURES_DIR/all_results.json" ]; then
  ALL_RESULTS_FILE="$FIGURES_DIR/all_results.json"
fi

export PAPER_DIR ROOT_DIR MAIN_FILE SECTIONS_DIR REFERENCES_FILE FIGURES_DIR
export RESULTS_FILE PROBLEM_ANALYSIS_FILE ALL_RESULTS_FILE NO_INTERNAL_CHECK
if [ "${#EXTRA_INTERNAL_TERMS[@]}" -gt 0 ]; then
  EXTRA_INTERNAL_TERMS_STR="$(printf '%s\n' "${EXTRA_INTERNAL_TERMS[@]}")"
else
  EXTRA_INTERNAL_TERMS_STR=""
fi
export EXTRA_INTERNAL_TERMS_STR

python3 - <<'PY'
import json
import os
import re
import sys
from pathlib import Path

exit_code = 0

def fail(msg):
    global exit_code
    print(f"FAIL: {msg}")
    exit_code = 1

def warn(msg):
    print(f"WARN: {msg}")

def info(msg):
    print(f"INFO: {msg}")

def opt_path(name):
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None

paper = Path(os.environ["PAPER_DIR"])
root = Path(os.environ["ROOT_DIR"])
main = Path(os.environ["MAIN_FILE"])
sections_dir = opt_path("SECTIONS_DIR")
refs = opt_path("REFERENCES_FILE")
figures_dir = opt_path("FIGURES_DIR")
results_file = opt_path("RESULTS_FILE")
problem_analysis = opt_path("PROBLEM_ANALYSIS_FILE")
all_results = opt_path("ALL_RESULTS_FILE")
no_internal_check = os.environ.get("NO_INTERNAL_CHECK") == "1"
extra_internal_terms = [
    item for item in os.environ.get("EXTRA_INTERNAL_TERMS_STR", "").splitlines()
    if item.strip()
]

def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")

def rel(path):
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)

def extract_calls(text, name):
    calls = []
    pattern = re.compile(r"#" + re.escape(name) + r"\s*\(")
    for match in pattern.finditer(text):
        open_pos = text.find("(", match.start())
        depth = 0
        in_string = False
        escape = False
        for idx in range(open_pos, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    calls.append((match.start(), idx + 1, text[open_pos + 1:idx]))
                    break
    return calls

def remove_spans(text, spans):
    if not spans:
        return text
    parts = []
    last = 0
    for start, end, _ in spans:
        parts.append(text[last:start])
        last = end
    parts.append(text[last:])
    return "".join(parts)

def unique_paths(paths):
    seen = set()
    out = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            out.append(path)
            seen.add(key)
    return out

def section_sort_key(path):
    match = re.match(r"^(\d+)[_-](.*)$", path.name)
    if match:
        return (0, int(match.group(1)), match.group(2))
    return (1, path.name)

info(f"paper dir: {paper}")
info(f"root dir: {root}")
info(f"main file: {main}")
if sections_dir:
    info(f"sections dir: {sections_dir}")
if figures_dir:
    info(f"figures dir: {figures_dir}")
if results_file:
    info(f"results file: {results_file}")

if not paper.exists():
    fail(f"paper directory not found: {paper}")

if not main.exists():
    fail(f"missing main paper file: {main}")
    sys.exit(exit_code)

# Detect engine by main file extension
is_latex = main.suffix == ".tex"
is_typst = main.suffix == ".typ"
engine_name = "LaTeX" if is_latex else "Typst"
info(f"detected engine: {engine_name} (main suffix: {main.suffix})")

main_text = read(main)

# Section file extension matches engine
section_ext = "*.tex" if is_latex else "*.typ"
if sections_dir and sections_dir.exists():
    section_files = sorted(sections_dir.glob(section_ext), key=section_sort_key)
elif paper.exists():
    excluded = {main.resolve()}
    if refs:
        excluded.add(refs.resolve())
    section_files = [
        path for path in sorted(paper.rglob(section_ext), key=section_sort_key)
        if path.resolve() not in excluded
    ]
    if section_files:
        warn(f"sections dir not supplied/found; using other {section_ext} files under paper dir as body sections")
else:
    section_files = []

info(f"section file count: {len(section_files)}")
if not section_files:
    warn(f"no separate section {section_ext} files detected; treating paper as a single-file {engine_name} document")

# Include/input detection: Typst uses #include("..."), LaTeX uses \input{...} or \include{...}
if is_typst:
    include_re = re.compile(r'#include\(\s*"([^"]+\.typ)"\s*\)')
    includes = include_re.findall(main_text)
else:
    include_re = re.compile(r'\\(?:input|include)\s*\{([^}]+)\}')
    raw_includes = [inc.strip() for inc in include_re.findall(main_text)]
    # LaTeX \input{name} may omit .tex extension; normalize by appending .tex if missing
    includes = [inc if inc.endswith(".tex") else inc + ".tex" for inc in raw_includes]
include_paths = [(main.parent / inc).resolve() for inc in includes]
include_names = [Path(inc).name for inc in includes]

info(f"main include count: {len(includes)}")
seen = set()
for name in include_names:
    if name in seen:
        fail(f"duplicate {engine_name} include: {name}")
    seen.add(name)

for inc, path in zip(includes, include_paths):
    if not path.exists():
        fail(f"included {engine_name} file does not exist: {inc}")

actual_names = [path.name for path in section_files]
if includes:
    included_set = set(include_names)
    for name in actual_names:
        if name not in included_set and not name.startswith("A_"):
            warn(f"body section file not included by main: {name}")
else:
    warn(f"main has no include/input calls; skip include order checks")

def leading_number(name):
    match = re.match(r"^(\d+)[_-]", name)
    return int(match.group(1)) if match else None

numbers = [leading_number(name) for name in include_names if leading_number(name) is not None]
if numbers and numbers != sorted(numbers):
    fail(f"section include order is not ascending: {numbers}")
if numbers:
    expected = list(range(min(numbers), max(numbers) + 1))
    missing = [num for num in expected if num not in numbers]
    if missing:
        warn(f"numbered section sequence has gaps: {missing}")

if problem_analysis and problem_analysis.exists():
    pa = read(problem_analysis)
    problem_hits = re.findall(r"(?:子问题|问题)\s*[一二三四五六七八九十0-9]+", pa)
    expected_problem_count = len(set(problem_hits))
    paper_problem_sections = [name for name in include_names or actual_names if re.search(r"problem|问题|q\d", name, re.I)]
    if expected_problem_count and paper_problem_sections and len(paper_problem_sections) < min(expected_problem_count, 3):
        warn(
            "paper problem sections may be fewer than analysis subproblems: "
            f"paper={len(paper_problem_sections)}, analysis={expected_problem_count}"
        )
else:
    info("problem analysis file not supplied/found; skip subproblem count check")

placeholder_re = re.compile(r"PLACEHOLDER|TODO|TBD|XXX|待补充|待续写|这里补|示例数据|待完善")
default_internal_terms = [
    "RESULTS_REPORT",
    "ANALYSIS_MODELING_REPORT.md",
    "PROBLEM_ANALYSIS.md",
    "CLAUDE.md",
    "figures/*.json",
    "_tmp/",
]
internal_terms = default_internal_terms + extra_internal_terms
if results_file:
    internal_terms.append(results_file.name)
if problem_analysis:
    internal_terms.append(problem_analysis.name)
if all_results:
    internal_terms.append(all_results.name)
internal_terms = sorted(set(term for term in internal_terms if term))
internal_re = re.compile("|".join(re.escape(term) for term in internal_terms)) if internal_terms else None

typ_files = unique_paths([main] + section_files + ([refs] if refs and refs.exists() else []) + sorted(paper.glob(section_ext)))
file_texts = []
combined = []
section_titles = []

for path in typ_files:
    if not path.exists():
        continue
    text = read(path)
    file_texts.append((path, text))
    combined.append(text)
    path_rel = rel(path)

    if placeholder_re.search(text):
        fail(f"placeholder text remains in {path_rel}")

    is_appendix = path.name.startswith("A_") or "appendix" in path.name.lower()
    if not no_internal_check and internal_re and internal_re.search(text):
        if is_appendix:
            warn(f"internal workflow term appears in appendix: {path_rel}")
        else:
            fail(f"internal workflow term leaked into paper text: {path_rel}")

    if path in section_files:
        body = text.strip()
        info(f"section length: {path.name} {len(body)} chars")
        if len(body) < 800 and not path.name.startswith("A_"):
            warn(f"section is short: {path.name} ({len(body)} chars)")

        # Auxiliary sections (appendix code, abstracts, appendices) may
        # legitimately omit a level-1 heading because the title is rendered
        # by main.typ/main.tex directly.
        lower_name = path.name.lower()
        is_aux_section = (
            path.name.startswith("A_")
            or lower_name.startswith("abstract")
            or lower_name.startswith("appendices")
        )

        if is_typst:
            # Typst heading check: `= Title` (space after =)
            malformed_headings = [
                line.strip()
                for line in text.splitlines()
                if re.match(r"^={1,6}(?![=\s]).+", line)
            ]
            for line in malformed_headings[:5]:
                fail(f"Typst heading is missing a space after '=' in {path.name}: {line[:80]}")
            heading = re.search(r"(?m)^=\s+.+", text)
            if not heading and not is_aux_section:
                fail(f"section has no level-1 Typst heading: {path.name}")
            if heading:
                title = heading.group(0).lstrip("= ").strip()
                section_titles.append((path.name, title))
                if re.search(r"problem\d+|q\d", path.name, re.I) and not re.search(r"问题|Problem|Question", title, re.I):
                    warn(f"problem section title may not match filename: {path.name} -> {title}")
            if re.search(r"(?m)^={3,}\s+", text):
                warn(f"deep heading level appears in section: {path.name}")
            list_count = len(re.findall(r"#(?:enum|list)\s*\(", text))
            if list_count >= 3:
                warn(f"many lists in section, consider prose: {path.name} ({list_count})")
            figure_calls = extract_calls(text, "figure")
            text_without_figures = remove_spans(text, figure_calls)
            if len(figure_calls) >= 2 and len(text_without_figures.strip()) < 1000:
                warn(f"many figures but little surrounding prose: {path.name}")
        else:
            # LaTeX heading check: \section{...}
            section_headings = re.findall(r"\\section\{([^}]*)\}", text)
            subsection_headings = re.findall(r"\\subsection\{([^}]*)\}", text)
            if not section_headings and not subsection_headings and not is_aux_section:
                fail(f"section has no \\section{{}} heading: {path.name}")
            for title in section_headings:
                section_titles.append((path.name, title))
                if re.search(r"problem\d+|q\d", path.name, re.I) and not re.search(r"问题|Problem|Question", title, re.I):
                    warn(f"problem section title may not match filename: {path.name} -> {title}")
            list_count = len(re.findall(r"\\begin\{(?:itemize|enumerate)\}", text))
            if list_count >= 3:
                warn(f"many lists in section, consider prose: {path.name} ({list_count})")
            figure_env_count = len(re.findall(r"\\begin\{figure\}", text))
            if figure_env_count >= 2 and len(text) < 2000:
                warn(f"many figures but little surrounding prose: {path.name}")

paper_text = "\n".join(combined)

if section_titles:
    info("section title order:")
    for idx, (name, title) in enumerate(section_titles, 1):
        info(f"  {idx}. {name} -> {title}")
    titles = [title for _, title in section_titles]
    if len(titles) != len(set(titles)):
        fail("duplicate level-1 section titles detected")

# Image reference check: Typst uses image("..."), LaTeX uses \includegraphics{...}
if is_typst:
    image_re = re.compile(r'image\(\s*"([^"]+)"')
else:
    image_re = re.compile(r'\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
referenced_images = []  # (source_path, resolved_target) for figures actually cited in body
for path, text in file_texts:
    for ref in image_re.findall(text):
        target = (path.parent / ref).resolve()
        if not target.exists():
            fail(f"referenced image does not exist from {rel(path)}: {ref}")
        else:
            referenced_images.append((path, target))

if figures_dir and figures_dir.exists():
    for fig in sorted(figures_dir.glob("*.pdf")):
        if fig.name not in paper_text:
            warn(f"figure PDF not referenced in paper: {fig.name}")
else:
    info("figures dir not supplied/found; skip unused figure check")

# Figure caption check
if is_typst:
    for _, _, body in extract_calls(paper_text, "figure"):
        if "caption:" not in body:
            fail("figure without caption")
            continue
        cap_match = re.search(r"caption:\s*\[(.*?)\]", body, re.S)
        if cap_match:
            cap = re.sub(r"\s+", " ", cap_match.group(1)).strip()
            if len(cap) > 80:
                warn(f"long figure caption: {cap[:80]}...")
            if len(cap) < 4:
                warn("very short figure caption")
else:
    # LaTeX: check \begin{figure}...\end{figure} blocks contain \caption{}
    figure_blocks = re.findall(r"\\begin\{figure\}.*?\\end\{figure\}", paper_text, re.S)
    for block in figure_blocks:
        cap_match = re.search(r"\\caption\{([^}]*)\}", block)
        if not cap_match:
            fail("LaTeX figure without \\caption{}")
            continue
        cap = re.sub(r"\s+", " ", cap_match.group(1)).strip()
        if len(cap) > 80:
            warn(f"long figure caption: {cap[:80]}...")
        if len(cap) < 4:
            warn("very short figure caption")

if refs and refs.exists():
    refs_text = read(refs)
    if len(refs_text.strip()) < 80:
        warn(f"{rel(refs)} looks very short")
    if is_typst:
        citation_re = r"@\w[\w:-]*|#cite\("
    else:
        citation_re = r"\\cite\w*\{[^}]+\}"
    if re.search(citation_re, paper_text):
        info("citation markers detected")
    else:
        warn(f"{rel(refs)} exists but no citation markers detected in paper")
else:
    warn("references file not supplied/found; skip reference completeness check")

if results_file and results_file.exists():
    results_text = read(results_file)
    metric_names = re.findall(
        r"(?i)\b(?:rmse|mae|mape|r2|score|objective|accuracy|precision|recall|f1|"
        r"权重|目标值|误差|得分)\b",
        results_text,
    )
    if metric_names and not any(name.lower() in paper_text.lower() for name in metric_names[:20]):
        warn("metrics appear in result file but are hard to find in paper text")
else:
    info("results file not supplied/found; skip metric consistency scan")

if all_results and all_results.exists():
    try:
        data = json.loads(read(all_results))
        nums = []

        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, (int, float)):
                nums.append(value)

        walk(data)
        key_nums = []
        for num in nums[:100]:
            if abs(num) >= 1:
                key_nums.append(str(round(num, 4)).rstrip("0").rstrip("."))
        if key_nums and not any(num and num in paper_text for num in key_nums[:30]):
            warn("numeric values from all-results JSON are hard to find in paper")
    except Exception as exc:
        warn(f"cannot parse all-results JSON: {exc}")
else:
    info("all-results JSON not supplied/found; skip JSON numeric scan")

# ============================================================================
# 实质性门禁（form 之外的 substance 检查）
# 这些检查针对历史上被"形式通过、实质不合格"漏过的硬伤：
#   A. 写死的 图N/表N/式N 编号引用（应改用 \ref/@ref，否则图表重排即错位）
#   B. 中文论文的数据图却用英文坐标轴/图例（观感"半成品"，国奖硬伤）
#   C. 缺少技术路线图/示意图（4drawio 阶段被跳过的信号）
#   D. 缺少"模型评价与推广"章节
# ============================================================================

# 论文语言判定：CJK 字符数明显占优即判为中文论文。
cjk_chars = re.findall(r"[\u4e00-\u9fff]", paper_text)
latin_words = re.findall(r"[A-Za-z]{2,}", paper_text)
is_chinese_paper = len(cjk_chars) > max(50, len(latin_words))
info(f"paper language: {'Chinese' if is_chinese_paper else 'non-Chinese'} "
     f"(CJK={len(cjk_chars)}, latin_words={len(latin_words)})")

# ---- A. 写死的 图N / 表N / 式N 编号引用 ----
# 正确写法：LaTeX `图~\ref{fig:x}`、Typst `@fig-x` —— 编号由交叉引用生成。
# 错误写法：`图1`、`图 2`、`表~3`、`式(4)` —— 手写数字，图表一重排就错位，
# 且极易出现"正文说图1是示意图，实际图1是别的图"的语义错位。
# 说明：附件1/附件2 等赛题给定的数据文件名不在此列（不匹配 图/表/式 前缀）；
#       仅扫描正文 section 文件，排除模板入口(main)、参考文献与附录，并剥离注释。
def strip_comments(text):
    if is_typst:
        return re.sub(r"(?<!:)//.*", "", text)  # Typst 行注释（避免误伤 URL 的 ://）
    return re.sub(r"(?<!\\)%.*", "", text)       # LaTeX 行注释（保留转义的 \%）

hardcoded_ref_re = re.compile(r"(图|表|式)\s*~?\s*\(?\s*([0-9]+)")
hardcoded_hits = []
for path, text in file_texts:
    if path not in section_files:
        continue  # 只查正文章节，跳过模板入口/参考文献
    if path.name.startswith("A_"):
        continue  # 附录代码不计
    for m in hardcoded_ref_re.finditer(strip_comments(text)):
        snippet = re.sub(r"\s+", " ", text[max(0, m.start() - 15):m.end() + 5]).strip()
        hardcoded_hits.append((path.name, m.group(1) + m.group(2), snippet))
if hardcoded_hits:
    fail(f"发现 {len(hardcoded_hits)} 处写死的图/表/式编号引用（应改用 \\ref/@ref 交叉引用）：")
    for name, tok, snip in hardcoded_hits[:12]:
        print(f"       - {name}: 「{tok}」… {snip}")
    if len(hardcoded_hits) > 12:
        print(f"       -（另有 {len(hardcoded_hits) - 12} 处）")

# ---- B. 中文论文的数据图却用英文标签 ----
# 判据：对每张被正文引用的图 PDF，用 pdftotext 提取可读文字。matplotlib 的中文
# 通常无法被 pdftotext 还原为 Unicode（提取为空），但英文坐标轴/图例能稳定提取。
# 因此"提取出大量长英文词"即强烈指示该图使用英文标注 —— 中文论文视为硬伤。
import shutil
import subprocess

pdftotext_bin = shutil.which("pdftotext")
# 允许在中文图里少量出现的英文技术记号（不计入英文词计数）。
_ALLOWED_FIG_EN = {
    "rmse", "mape", "bootstrap", "airy", "cauchy", "snell", "fresnel",
    "fabry", "perot",
}
if is_chinese_paper and pdftotext_bin and referenced_images:
    checked = set()
    english_figs = []
    for _, target in referenced_images:
        if target in checked or target.suffix.lower() != ".pdf":
            continue
        checked.add(target)
        try:
            out = subprocess.run(
                [pdftotext_bin, str(target), "-"],
                capture_output=True, encoding="utf-8", errors="ignore", timeout=30,
            ).stdout or ""
        except Exception:
            continue
        words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", out)}
        words -= _ALLOWED_FIG_EN
        if len(words) >= 5:
            english_figs.append((target.name, sorted(words)[:10]))
    if english_figs:
        fail(f"中文论文中有 {len(english_figs)} 张图疑似使用英文坐标轴/图例"
             f"（应改用中文，见 3coding-visual/scripts/mpl_setup.py）：")
        for fname, ws in english_figs[:12]:
            print(f"       - {fname}: {ws}")
elif is_chinese_paper and not pdftotext_bin:
    info("pdftotext 不可用，跳过图内英文标签检查（建议安装 poppler-utils 以启用）")

# ---- B2. 作图源码是否配置中文字体（二级网，源码层）----
# 即使 PDF 检查因故跳过，也从作图脚本判断是否设置了中文字体。
if is_chinese_paper:
    py_fig_sources = []
    for base in [root / "code", root / "scripts", root / "figures", root]:
        if base.exists():
            py_fig_sources += list(base.rglob("*.py"))
    fig_scripts = [
        p for p in py_fig_sources
        if re.search(r"matplotlib|pyplot|savefig|plt\.", read(p))
    ]
    if fig_scripts:
        cjk_font_re = re.compile(
            r"apply_chinese_style|mpl_setup|SimHei|微软雅黑|Microsoft YaHei|"
            r"Noto Sans CJK|Source Han|WenQuanYi|Heiti|Songti|font\.sans-serif"
        )
        configured = [p for p in fig_scripts if cjk_font_re.search(read(p))]
        if not configured:
            warn(f"检测到 {len(fig_scripts)} 个 matplotlib 作图脚本，但均未配置中文字体"
                 f"（应 import mpl_setup; apply_chinese_style()）")

# ---- C. 技术路线图 / 示意图是否存在 ----
# 竞赛论文通常需要至少一张技术路线图；物理/结构类题目还需光路/结构示意图。
# 4drawio 阶段负责这些非数据图；整个阶段被跳过时此项会缺失。
schematic_kw = re.compile(
    r"roadmap|flow|pipeline|schematic|diagram|structure|"
    r"路线|流程|示意|结构|框架|机理|原理", re.I)
schematic_found = False
schematic_pool = list(referenced_images)
if figures_dir and figures_dir.exists():
    schematic_pool += [(figures_dir, p) for p in figures_dir.rglob("*.pdf")]
    schematic_pool += [(figures_dir, p) for p in figures_dir.rglob("*.drawio")]
for _, target in schematic_pool:
    if schematic_kw.search(target.name):
        schematic_found = True
        break
if not schematic_found and re.search(r"问题|模型|建模", paper_text):
    warn("未发现技术路线图/流程图/示意图（文件名含 roadmap/flow/路线/流程/示意/结构 等）；"
         "竞赛论文通常需要技术路线图，物理/结构题还需原理或光路示意图（见 4drawio）")

# ---- D. 模型评价与推广章节 ----
if is_chinese_paper and not re.search(
    r"模型评价|模型的评价|模型检验|优缺点|模型推广|模型改进|误差分析", paper_text):
    warn("未发现'模型评价/优缺点/模型推广/误差分析'相关章节；国奖论文通常单列'模型评价与推广'")

if exit_code == 0:
    print("PASS: writing text gate passed")
else:
    print("FAIL: writing text gate failed")

sys.exit(exit_code)
PY
