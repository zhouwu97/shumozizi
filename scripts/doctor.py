"""检查唯一仓库根、Python 包、Schema 与 PDF 工具。"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from jsonschema import Draft202012Validator

from shumozizi.core.repo_root import (
    assert_workspace_opened_at_repo_root,
    resolve_repo_root,
)


def diagnostic(name: str, status: str, details: str) -> dict[str, str]:
    """构造稳定的诊断记录。"""
    return {"name": name, "status": status, "details": details}


def guarded(name: str, callback: Callable[[], str]) -> dict[str, str]:
    """把诊断异常转为 error 项。"""
    try:
        return diagnostic(name, "ok", callback())
    except Exception as exc:
        return diagnostic(name, "error", str(exc))


def check_command(name: str, command: str) -> dict[str, str]:
    """读取外部命令版本；缺少可选命令只警告。"""
    executable = shutil.which(command)
    if not executable:
        return diagnostic(name, "warn", "未在 PATH 中找到")
    completed = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    line = (completed.stdout or completed.stderr).splitlines()
    return diagnostic(
        name,
        "ok" if completed.returncode == 0 else "warn",
        line[0] if line else str(completed.returncode),
    )


def collect_diagnostics() -> list[dict[str, str]]:
    """收集不修改项目状态的环境诊断。"""
    checks = [
        guarded(
            "Codex workspace root",
            lambda: assert_workspace_opened_at_repo_root() or str(Path.cwd().resolve()),
        ),
        guarded("Repository root", lambda: str(resolve_repo_root())),
        diagnostic(
            "Python", "ok" if sys.version_info >= (3, 12) else "error", sys.version.split()[0]
        ),
    ]
    root: Path | None = None
    try:
        root = resolve_repo_root(Path(__file__))
        schemas = sorted((root / "schemas").glob("*.schema.json"))
        for path in schemas:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
        checks.append(diagnostic("JSON Schemas", "ok", f"{len(schemas)} 个文件"))
    except Exception as exc:
        checks.append(diagnostic("JSON Schemas", "error", str(exc)))
    for package in ("shumozizi", "jsonschema", "rfc8785", "pypdf"):
        try:
            importlib.import_module(package)
            checks.append(
                diagnostic(
                    f"Python package: {package}",
                    "ok",
                    importlib.metadata.version(package),
                )
            )
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            checks.append(diagnostic(f"Python package: {package}", "error", str(exc)))
    if root is not None:
        conflicts = [
            parent / "AGENTS.md" for parent in root.parents if (parent / "AGENTS.md").is_file()
        ]
        detail = "父级规则位于已隔离的工作区边界外" if conflicts else "未发现父级冲突规则"
        checks.append(diagnostic("Parent AGENTS isolation", "ok", detail))
    checks.extend([check_command("Typst", "typst"), check_command("PDFInfo", "pdfinfo")])
    return checks


def main() -> int:
    """输出诊断并以错误项决定退出码。"""
    checks = collect_diagnostics()
    for item in checks:
        print(f"[{item['status'].upper()}] {item['name']}: {item['details']}")
    return 1 if any(item["status"] == "error" for item in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
