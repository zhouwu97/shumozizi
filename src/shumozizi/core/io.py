"""提供边界安全、可复验的文件与 JSON 原语。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """表示运行时文件不满足协议。"""


def load_json(path: Path) -> dict[str, Any]:
    """读取根节点为对象的 UTF-8 JSON。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"缺少文件: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"JSON 格式错误 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON 根节点必须是对象: {path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """在同一目录落盘并原子替换 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    """分块计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    """计算字节串 SHA-256。"""
    return hashlib.sha256(value).hexdigest()


def sha256_tree(path: Path) -> str:
    """按相对路径和内容稳定计算文件或目录摘要。"""
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise ContractError(f"哈希目标不存在: {path}")
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def resolve_inside(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    """解析根内相对路径并拒绝绝对路径及目录穿越。"""
    candidate_input = Path(relative)
    if candidate_input.is_absolute() or not relative.strip():
        raise ContractError(f"必须使用非空相对路径: {relative}")
    resolved_root = root.resolve()
    candidate = (resolved_root / candidate_input).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ContractError(f"路径越过运行目录边界: {relative}")
    if must_exist and not candidate.is_file():
        raise ContractError(f"文件不存在: {relative}")
    return candidate
