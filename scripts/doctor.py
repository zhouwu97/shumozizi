"""跨平台检查数学建模工作流所需的本地环境。"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "schemas"
RUNS_ROOT = REPO_ROOT / "runs"
MINIMUM_PYTHON = (3, 10)


def diagnostic(name: str, status: str, details: str) -> dict[str, str]:
    """构造稳定的诊断记录。"""
    return {"name": name, "status": status, "details": details}


def check_python() -> dict[str, str]:
    """检查当前 Python 是否达到项目最低版本。"""
    current = sys.version_info[:3]
    status = "ok" if current >= MINIMUM_PYTHON else "error"
    return diagnostic("Python", status, ".".join(str(part) for part in current))


def check_package(import_name: str, *, required: bool) -> dict[str, str]:
    """检查 Python 包能否导入。"""
    try:
        module = importlib.import_module(import_name)
    except ImportError as exc:
        return diagnostic(
            f"Python package: {import_name}",
            "error" if required else "warn",
            f"不可导入: {exc}",
        )
    version = getattr(module, "__version__", "已安装")
    return diagnostic(f"Python package: {import_name}", "ok", str(version))


def check_command(
    name: str,
    command: str,
    *,
    version_args: tuple[str, ...] = ("--version",),
    required: bool = False,
) -> dict[str, str]:
    """检查可选排版或 PDF 命令，并读取一行版本信息。"""
    executable = shutil.which(command)
    if not executable:
        return diagnostic(name, "error" if required else "warn", "未在 PATH 中找到")
    try:
        completed = subprocess.run(
            [executable, *version_args],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return diagnostic(name, "error" if required else "warn", f"无法执行: {exc}")
    version_text = (completed.stdout or completed.stderr).splitlines()
    details = version_text[0].strip() if version_text else f"退出码 {completed.returncode}"
    status = "ok" if completed.returncode == 0 else ("error" if required else "warn")
    return diagnostic(name, status, details)


def check_runs_writable() -> dict[str, str]:
    """通过临时文件确认 runs 目录可写，并立即清理。"""
    try:
        RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".doctor-",
            suffix=".tmp",
            dir=RUNS_ROOT,
            delete=True,
        ) as stream:
            stream.write("writable")
            stream.flush()
        return diagnostic("runs writable", "ok", str(RUNS_ROOT))
    except OSError as exc:
        return diagnostic("runs writable", "error", str(exc))


def check_schemas() -> dict[str, str]:
    """检查全部 Schema 自身是否符合 Draft 2020-12。"""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        return diagnostic("JSON Schemas", "error", f"无法加载 jsonschema: {exc}")

    schema_paths = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    if not schema_paths:
        return diagnostic("JSON Schemas", "error", "未找到 Schema 文件")
    errors: list[str] = []
    for path in schema_paths:
        try:
            schema: Any = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    if errors:
        return diagnostic("JSON Schemas", "error", "; ".join(errors))
    return diagnostic("JSON Schemas", "ok", f"{len(schema_paths)} 个文件")


def collect_diagnostics() -> list[dict[str, str]]:
    """收集核心、建模与排版工具诊断。"""
    checks = [
        check_python(),
        check_package("jsonschema", required=True),
        check_runs_writable(),
        check_schemas(),
    ]
    for package in ("numpy", "pandas", "matplotlib", "sklearn"):
        checks.append(check_package(package, required=False))
    checks.extend(
        [
            check_command("Typst", "typst"),
            check_command("XeLaTeX", "xelatex"),
            check_command("PDFInfo", "pdfinfo", version_args=("-v",)),
        ]
    )
    return checks


def main() -> int:
    """输出人类可读结果，并以错误项决定退出码。"""
    checks = collect_diagnostics()
    for item in checks:
        print(f"[{item['status'].upper()}] {item['name']}: {item['details']}")
    return 1 if any(item["status"] == "error" for item in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
