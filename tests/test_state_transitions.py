"""验证人工终稿确认前仍可返回定向修复。"""

from shumozizi.workflow.state_service import TRANSITIONS, WorkflowEvent


def test_waiting_final_can_return_to_paper_fix() -> None:
    """视觉复核发现问题时不得被终稿等待状态锁死。"""
    assert TRANSITIONS[("WAITING_HUMAN_FINAL", WorkflowEvent.FIX_APPLIED)] == "PAPER_DRAFTED"
