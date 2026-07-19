"""创新主张的结构化证据评估。"""

from .evaluator import (
    EVALUATOR_VERSION,
    evaluate_claim_documents,
    evaluate_claims,
    evidence_is_stale,
)

__all__ = [
    "EVALUATOR_VERSION",
    "evaluate_claim_documents",
    "evaluate_claims",
    "evidence_is_stale",
]
