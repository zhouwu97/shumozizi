"""以不可伪造的标记文件定位唯一仓库根。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT_MARKER = ".shumozizi-root"


class RepositoryRootError(RuntimeError):
    """表示仓库根缺失、冲突或工作区打开位置错误。"""


def _candidate_directories(start: Path) -> list[Path]:
    """返回用于查找根标记的当前目录及所有父目录。"""
    resolved = start.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    return [resolved, *resolved.parents]


def resolve_repo_root(start: Path | None = None) -> Path:
    """从给定位置向上查找唯一仓库根。

    Args:
        start: 起始文件或目录；省略时使用当前工作目录。

    Returns:
        含根标记与 ``.git`` 的绝对路径。

    Raises:
        RepositoryRootError: 找不到合法根或发现嵌套根冲突。
    """
    origin = Path.cwd() if start is None else Path(start)
    matches = [path for path in _candidate_directories(origin) if (path / ROOT_MARKER).is_file()]
    if not matches:
        raise RepositoryRootError(f"从 {origin.resolve()} 向上未找到 {ROOT_MARKER}")
    root = matches[0]
    assert_repo_root(root)
    return root


def assert_repo_root(path: Path) -> None:
    """断言路径就是唯一 Git 仓库根。

    Args:
        path: 待检查路径。

    Raises:
        RepositoryRootError: 标记、Git 元数据或 Git 根不匹配。
    """
    resolved = path.resolve()
    if not (resolved / ROOT_MARKER).is_file():
        raise RepositoryRootError(f"缺少仓库根标记: {resolved / ROOT_MARKER}")
    if not (resolved / ".git").exists():
        raise RepositoryRootError(f"目标不是 Git 根: {resolved}")
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=resolved,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RepositoryRootError(f"无法解析 Git 根: {completed.stderr.strip()}")
    git_root = Path(completed.stdout.strip()).resolve()
    if git_root != resolved:
        raise RepositoryRootError(f"标记根 {resolved} 与 Git 根 {git_root} 不一致")


def workspace_start_directory() -> Path:
    """返回 Codex 启动目录；测试可用专用环境变量显式覆盖。"""
    configured = os.environ.get("SHUMOZIZI_WORKSPACE_ROOT")
    return Path(configured).resolve() if configured else Path.cwd().resolve()


def assert_workspace_opened_at_repo_root() -> None:
    """要求 Codex 直接以嵌套 Git 根打开，而非从冲突父目录进入。

    Raises:
        RepositoryRootError: 启动目录不是目标 Git 根，或父目录存在规则冲突。
    """
    expected = resolve_repo_root(Path(__file__))
    opened = workspace_start_directory()
    if opened != expected:
        raise RepositoryRootError(
            f"工作区启动目录必须是 {expected}，当前为 {opened}；请直接打开嵌套 Git 根"
        )
    # 直接打开目标根时，父级 AGENTS.md 位于工作区边界之外，不参与规则解析。
