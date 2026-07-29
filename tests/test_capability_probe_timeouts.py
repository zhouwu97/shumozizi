"""验证本地数值引擎使用符合冷启动成本的探测超时。"""

from __future__ import annotations

from unittest.mock import Mock, patch

from shumozizi.simple import capabilities


def test_matlab_probe_uses_long_cold_start_timeout() -> None:
    """MATLAB 不应因复用 Python 的短超时而被误判为不可用。"""
    completed = Mock(returncode=0, stdout="R2024a", stderr="")
    capabilities._PROBE_CACHE.clear()

    with patch("shumozizi.simple.capabilities.subprocess.run", return_value=completed) as run:
        capabilities._run_probe(
            ["matlab", "-batch", "disp(version)"],
            timeout_seconds=capabilities._PROBE_TIMEOUT_SECONDS["matlab"],
        )

    assert run.call_args.kwargs["timeout"] == 60
    assert capabilities._PROBE_TIMEOUT_SECONDS["python"] == 12


def test_matlab_engine_probe_does_not_require_optimization_toolbox() -> None:
    """基础可用性不能因缺少 fmincon 而否决 MATLAB 的仿真、矩阵或绘图角色。"""
    command = capabilities._engine_probe_command("matlab", "matlab")

    assert command[:2] == ["matlab", "-batch"]
    assert "disp(version)" in command[2]
    assert "fmincon" not in command[2]
