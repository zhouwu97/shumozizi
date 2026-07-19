"""论文主张使用权限与证据门禁。"""

from .gate import (
    gate_contribution_claims,
    gate_paper_claims,
    require_paper_claim_allowed,
)
from .receipts import verify_figure_receipts, verify_paper_build_receipt, verify_production_receipts

__all__ = [
    "gate_contribution_claims",
    "gate_paper_claims",
    "require_paper_claim_allowed",
    "verify_figure_receipts",
    "verify_paper_build_receipt",
    "verify_production_receipts",
]
