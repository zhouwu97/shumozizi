"""验证论文展示精度不会超过综合误差所支持的位数。"""

from __future__ import annotations

import pytest

from shumozizi.core.io import ContractError
from shumozizi.evidence.validator import _validate_precision_policy


def _map(decimals: int, *, uncertainty: float = 0.001486) -> dict:
    """构造只用于精度语义检查的 evidence map。"""
    return {
        "schema_name": "evidence_map",
        "schema_version": "2.1",
        "run_id": "precision-test",
        "precision_policy": {
            "model_error": 0.0,
            "discretization_error": 0.001,
            "independent_validation_difference": 0.001486,
            "combined_uncertainty": uncertainty,
            "rounding_rule": "max_error_bound",
        },
        "claims": [
            {
                "claim_id": "duration",
                "inputs": [],
                "display": {"decimals": decimals, "unit": "s"},
            }
        ],
    }


def test_six_decimals_are_rejected_when_uncertainty_only_supports_three() -> None:
    """0.001486 秒的综合差异不能展示为六位小数。"""
    with pytest.raises(ContractError, match="最多支持 3 位"):
        _validate_precision_policy(_map(6))


def test_three_decimals_are_allowed_by_same_precision_policy() -> None:
    """同一误差上界允许保守展示三位小数。"""
    _validate_precision_policy(_map(3))


def test_combined_uncertainty_cannot_hide_a_larger_component() -> None:
    """综合误差不能小于独立复算差异。"""
    payload = _map(3, uncertainty=0.001)
    with pytest.raises(ContractError, match="不能小于"):
        _validate_precision_policy(payload)
