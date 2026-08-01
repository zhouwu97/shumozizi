"""读取外部 Author 交付物并汇总外部写作状态。

外部 Author 的交付物固定位于 ``paper/external-author/``：

- ``draft.tex``：正文草稿，即使材料有缺口也必须返回；
- ``AUTHOR_NOTE.md``：可选写作说明；
- ``AUTHOR_REQUESTS.json``：可选的上游材料请求。

本模块只负责读取与校验；Import Audit 在 ``import_audit`` 中完成，请求决策
在后续版本中由 ``decide_author_request`` 负责。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, relative_inside, sha256_file
from shumozizi.simple.authoring import read_authoring

EXTERNAL_DIR = Path("paper/external-author")
DRAFT_PATH = EXTERNAL_DIR / "draft.tex"
AUTHOR_NOTE_PATH = EXTERNAL_DIR / "AUTHOR_NOTE.md"
AUTHOR_REQUESTS_PATH = EXTERNAL_DIR / "AUTHOR_REQUESTS.json"


def read_external_draft(run_dir: Path) -> dict[str, Any]:
    """读取外部 Author 交付物，并校验其位于运行目录内。

    Args:
        run_dir: 当前运行目录。

    Returns:
        含 ``draft_path``、``draft_text`` 与可选 note/requests 的读取结果。

    Raises:
        ContractError: 缺少 ``draft.tex``，或路径越界。
    """
    root = run_dir.resolve()
    draft = relative_inside(root, root / DRAFT_PATH)
    if not (root / DRAFT_PATH).is_file():
        raise ContractError("外部 Author 尚未返回 draft.tex")
    payload: dict[str, Any] = {
        "draft_path": draft.as_posix(),
        "draft_sha256": sha256_file(root / DRAFT_PATH),
        "draft_text": (root / DRAFT_PATH).read_text(encoding="utf-8"),
    }
    note = root / AUTHOR_NOTE_PATH
    if note.is_file():
        payload["author_note_path"] = relative_inside(root, note).as_posix()
        payload["author_note_sha256"] = sha256_file(note)
        payload["author_note_text"] = note.read_text(encoding="utf-8")
    requests = root / AUTHOR_REQUESTS_PATH
    if requests.is_file():
        payload["author_requests_path"] = relative_inside(root, requests).as_posix()
        payload["author_requests"] = load_json(requests)
    return payload


def external_author_status(run_dir: Path) -> dict[str, Any]:
    """汇总外部 Author 流程的当前状态（authoring + 草稿 + audit 存在性）。"""
    root = run_dir.resolve()
    authoring = read_authoring(root)
    status: dict[str, Any] = {
        "authoring_mode": authoring["authoring_mode"],
        "authoring_status": authoring["authoring_status"],
        "handoff_revision": authoring["handoff_revision"],
        "draft_present": (root / DRAFT_PATH).is_file(),
        "author_note_present": (root / AUTHOR_NOTE_PATH).is_file(),
        "author_requests_present": (root / AUTHOR_REQUESTS_PATH).is_file(),
        "import_audit_present": (root / "review/import-audit.json").is_file(),
        "confirmed_fact_failures_present": (
            root / "review/confirmed-scientific-fact-failures.json"
        ).is_file(),
    }
    audit_path = root / "review/import-audit.json"
    if audit_path.is_file():
        try:
            status["import_audit"] = load_json(audit_path)
        except ContractError:
            status["import_audit"] = None
    return status
