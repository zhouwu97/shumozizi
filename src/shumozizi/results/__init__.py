"""指标溯源、语义准入、封存与撤销。"""

from .semantics import require_candidate_semantics, validate_candidate_semantics

__all__ = ["require_candidate_semantics", "validate_candidate_semantics"]
