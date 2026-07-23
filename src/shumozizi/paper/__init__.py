"""论文主张使用权限与证据门禁。"""

from .compiler import compile_paper, verify_paper_compile_receipt
from .contributions import (
    build_contribution_ledger,
    require_math_innovation_allowed,
    verify_contribution_ledger,
)
from .gate import (
    gate_contribution_claims,
    gate_paper_claims,
    require_paper_claim_allowed,
)
from .receipts import verify_figure_receipts, verify_paper_build_receipt, verify_production_receipts
from .references import (
    register_paper_references,
    verify_paper_references,
    writing_reference_cards,
)
from .sufficiency import (
    assess_paper_sufficiency,
    build_content_blueprint,
    run_paper_sufficiency_check,
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
    "assess_paper_sufficiency",
    "build_content_blueprint",
    "run_paper_sufficiency_check",
    "verify_content_blueprint",
    "verify_figure_receipts",
    "verify_paper_build_receipt",
    "verify_production_receipts",
    "compile_paper",
    "verify_paper_compile_receipt",
]
