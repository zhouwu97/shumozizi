"""源码包测试夹具。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json, sha256_file


def write_source_package(run_dir: Path, *, question_id: str, result_id: str) -> Path:
    """生成同时绑定 Python、MATLAB 与当前论文事实的最小源码包。"""
    python_source = run_dir / "source/python/model.py"
    matlab_source = run_dir / "source/matlab/model.m"
    python_source.parent.mkdir(parents=True, exist_ok=True)
    matlab_source.parent.mkdir(parents=True, exist_ok=True)
    python_source.write_text("print(1)\n", encoding="utf-8")
    matlab_source.write_text("disp(1);\n", encoding="utf-8")
    plan = load_json(run_dir / "paper/paper_plan.json")
    entries = {
        "python": {
            "path": "source/python/model.py",
            "sha256": sha256_file(python_source),
            "run_command": "python source/python/model.py",
            "dependencies": [],
            "question_ids": [question_id],
            "supports": [{"kind": "accepted_result", "ref": result_id}],
        },
        "matlab": {
            "path": "source/matlab/model.m",
            "sha256": sha256_file(matlab_source),
            "run_command": "octave --quiet source/matlab/model.m",
            "dependencies": ["GNU Octave or MATLAB"],
            "question_ids": [question_id],
            "supports": [{"kind": "accepted_result", "ref": result_id}],
        },
    }
    path = run_dir / "source/SOURCE_MANIFEST.json"
    atomic_json(
        path,
        {
            "schema_name": "source_manifest",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "bindings": {
                "final_pdf": {
                    "path": plan["final_pdf_path"],
                    "sha256": sha256_file(run_dir / plan["final_pdf_path"]),
                },
                "paper_plan": {
                    "path": "paper/paper_plan.json",
                    "sha256": sha256_file(run_dir / "paper/paper_plan.json"),
                },
                "result_registry": {
                    "path": "results/result_registry.json",
                    "sha256": sha256_file(run_dir / "results/result_registry.json"),
                },
            },
            "sources": {"python": [entries["python"]], "matlab": [entries["matlab"]]},
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )
    return path
