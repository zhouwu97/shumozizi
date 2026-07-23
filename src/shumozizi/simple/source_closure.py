"""解析运行目录内 Python 入口的本地源码依赖闭包。"""

from __future__ import annotations

import ast
from pathlib import Path

from shumozizi.core.io import ContractError, relative_inside, resolve_inside


def _module_candidates(code_root: Path, module: str) -> list[Path]:
    """返回一个模块名在 ``code/`` 下可能对应的源码文件。"""
    if not module:
        return []
    parts = module.split(".")
    candidates: list[Path] = []
    for index in range(1, len(parts)):
        initializer = code_root.joinpath(*parts[:index], "__init__.py")
        if initializer.is_file():
            candidates.append(initializer)
    module_file = code_root.joinpath(*parts).with_suffix(".py")
    package_file = code_root.joinpath(*parts, "__init__.py")
    if module_file.is_file():
        candidates.append(module_file)
    if package_file.is_file():
        candidates.append(package_file)
    return candidates


def _module_name(path: Path, code_root: Path) -> tuple[str, ...]:
    """返回源码相对 ``code/`` 的模块路径片段。"""
    relative = path.relative_to(code_root)
    if relative.name == "__init__.py":
        return relative.parent.parts
    return relative.with_suffix("").parts


def _imported_local_files(path: Path, code_root: Path) -> set[Path]:
    """静态解析一个 Python 文件直接引用的本地模块。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ContractError(f"无法解析 Python 源码闭包: {path}") from exc
    current_module = _module_name(path, code_root)
    current_package = current_module if path.name == "__init__.py" else current_module[:-1]
    dependencies: set[Path] = set()
    for node in ast.walk(tree):
        module_names: list[str] = []
        if isinstance(node, ast.Import):
            module_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = max(0, len(current_package) - node.level + 1)
                prefix = current_package[:keep]
                base_parts = (*prefix, *((node.module or "").split(".") if node.module else ()))
            else:
                base_parts = tuple((node.module or "").split(".")) if node.module else ()
            base = ".".join(part for part in base_parts if part)
            if base:
                module_names.append(base)
            for alias in node.names:
                if alias.name != "*" and base:
                    module_names.append(f"{base}.{alias.name}")
        for module_name in module_names:
            dependencies.update(_module_candidates(code_root, module_name))
    return dependencies


def python_source_closure(run_dir: Path, source_script: str) -> list[str]:
    """递归返回入口脚本在 ``code/**/*.py`` 中的本地源码闭包。

    标准库和第三方包不属于运行目录内源码，因此不会进入闭包。非 Python
    入口只返回入口自身，供其他语言的独立引擎继续使用既有文件哈希边界。

    Args:
        run_dir: 当前 v3 运行目录。
        source_script: 运行目录内入口脚本相对路径。

    Returns:
        排序后的 POSIX 相对路径，包含入口自身。

    Raises:
        ContractError: 入口越界、缺失，或本地 Python 源码无法解析。
    """
    root = run_dir.resolve()
    entry = resolve_inside(root, source_script, must_exist=True)
    entry_relative = relative_inside(root, entry).as_posix()
    if entry.suffix.casefold() != ".py":
        return [entry_relative]
    code_root = (root / "code").resolve()
    if code_root not in entry.parents:
        return [entry_relative]
    closure: set[Path] = set()
    pending = [entry]
    while pending:
        current = pending.pop()
        if current in closure:
            continue
        closure.add(current)
        for dependency in _imported_local_files(current, code_root):
            resolved = dependency.resolve()
            if resolved not in closure:
                pending.append(resolved)
    return sorted(relative_inside(root, path).as_posix() for path in closure)
