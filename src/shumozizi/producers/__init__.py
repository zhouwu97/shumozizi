"""从锁定事实生成路线、模型规格、实验清单和论文骨架。"""

from .experiment import create_experiment_manifest
from .model_spec import create_model_spec
from .paper import create_paper_skeleton
from .route import write_route_candidates

__all__ = [
    "create_experiment_manifest",
    "create_model_spec",
    "create_paper_skeleton",
    "write_route_candidates",
]
