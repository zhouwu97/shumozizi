"""论文主张使用权限与证据门禁。"""

from .gate import (
    gate_contribution_claims,
    gate_paper_claims,
    require_paper_claim_allowed,
)

__all__ = [
    "gate_contribution_claims",
    "gate_paper_claims",
    "require_paper_claim_allowed",
]
