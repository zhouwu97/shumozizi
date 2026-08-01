"""论文主张使用权限与证据门禁。"""

from .compiler import (
    compile_longform_draft,
    compile_paper,
    compile_reviewable_draft,
    verify_longform_draft_receipt,
    verify_paper_compile_receipt,
    verify_reviewable_draft_receipt,
)
from .contributions import (
    build_contribution_ledger,
    require_math_innovation_allowed,
    verify_contribution_ledger,
)
from .editorial import (
    close_editorial_action,
    editorial_readiness,
    record_paper_cold_reader_actions,
    require_editorial_readiness,
)
from .evidence import (
    read_evidence_function_contract,
    review_evidence_functions,
    write_evidence_function_contract,
)
from .gate import (
    gate_contribution_claims,
    gate_paper_claims,
    require_paper_claim_allowed,
)
from .layout_optimizer import (
    build_layout_optimization,
    layout_optimization_freshness,
    read_layout_optimization,
)
from .page_budget import audit_page_budget, verify_page_budget
from .receipts import verify_figure_receipts, verify_paper_build_receipt, verify_production_receipts
from .references import (
    register_paper_references,
    verify_paper_references,
    writing_reference_cards,
)
from .storyboard import storyboard_progression_report
from .sufficiency import (
    assess_paper_structure_signals,
    build_content_blueprint,
    run_paper_structure_signal_check,
    verify_content_blueprint,
)

__all__ = [
    "gate_contribution_claims",
    "gate_paper_claims",
    "require_paper_claim_allowed",
    "register_paper_references",
    "verify_paper_references",
    "writing_reference_cards",
    "build_contribution_ledger",
    "require_math_innovation_allowed",
    "verify_contribution_ledger",
    "review_evidence_functions",
    "write_evidence_function_contract",
    "read_evidence_function_contract",
    "build_layout_optimization",
    "read_layout_optimization",
    "layout_optimization_freshness",
    "audit_page_budget",
    "verify_page_budget",
    "record_paper_cold_reader_actions",
    "close_editorial_action",
    "editorial_readiness",
    "require_editorial_readiness",
    "storyboard_progression_report",
    "assess_paper_structure_signals",
    "build_content_blueprint",
    "run_paper_structure_signal_check",
    "verify_content_blueprint",
    "verify_figure_receipts",
    "verify_paper_build_receipt",
    "verify_production_receipts",
    "compile_paper",
    "compile_longform_draft",
    "compile_reviewable_draft",
    "verify_paper_compile_receipt",
    "verify_longform_draft_receipt",
    "verify_reviewable_draft_receipt",
]
