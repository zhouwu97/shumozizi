"""生成 v3.4 Writer Handoff Package 的命令行入口。

正向路径（必须真实走通）：

    prepare_writer_handoff
    → 确保 authoring_mode=external_handoff
    → 幂等守卫：已有交接包且仍 fresh 时拒绝，避免 revision 空转
    → 素材池缺失或 stale 时自动重建（ensure_material_pool_current）
    → writer_handoff_readiness
    → build_writer_handoff（生成 6+1 交接包 + manifest，handoff_revision+1）
    → mark handoff_ready
    → mark waiting_external_author

材料不充分时输出 blocked 与具体原因（退出码 1）；成功时输出
``WRITER_HANDOFF_READY`` 并把 authoring_status 置为 ``waiting_external_author``。
结果、主张边界等输入更新后重跑会因 fresh 守卫自动放行并生成新 revision。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.paper.handoff import (  # noqa: E402
    HANDOFF_MANIFEST_PATH,
    build_writer_handoff,
    ensure_material_pool_current,
    mark_waiting_external_author,
    verify_handoff_freshness,
    writer_handoff_readiness,
)
from shumozizi.simple.authoring import (  # noqa: E402
    mark_authoring_status,
    read_authoring,
    set_authoring_mode,
)

EXTERNAL_REASON = "prepare_writer_handoff 显式启用外部写作交接"


def _ensure_external_and_handoff_ready(run_dir: Path) -> None:
    """推进 authoring 状态到 handoff_ready，供等待外部 Author。

    不修改正式结果或交接材料；只保证状态机不会停留在 preparing_handoff 而让
    ``mark_waiting_external_author`` 因迁移非法报错。
    """
    authoring = read_authoring(run_dir)
    if authoring["authoring_mode"] != "external_handoff":
        set_authoring_mode(run_dir, "external_handoff", reason=EXTERNAL_REASON)
    current = read_authoring(run_dir)["authoring_status"]
    if current == "preparing_handoff":
        mark_authoring_status(run_dir, "handoff_ready")
    elif current not in {"handoff_ready", "waiting_external_author"}:
        raise ContractError(
            f"当前 authoring_status={current}，不能再次准备外部 Author 交接；"
            "请先完成导入、裁决或显式回退"
        )
    # 幂等守卫：已有交接包且仍绑定最新材料时拒绝重建，避免 revision 空转；
    # 输入（结果、claim 边界、素材源）变化后 verify_handoff_freshness 会报
    # stale，此时放行重建并 revision+1。
    if (run_dir / HANDOFF_MANIFEST_PATH).is_file():
        freshness = verify_handoff_freshness(run_dir)
        if freshness.get("fresh"):
            raise ContractError(
                "交接包已是最新（revision "
                + str(freshness.get("handoff_revision", "?"))
                + "），且仍绑定当前材料；若材料已更新，请先更新结果或主张边界再重跑"
            )


def main() -> int:
    """构建交接包，并在成功后进入等待外部 Author 状态。"""
    parser = argparse.ArgumentParser(description="准备 v3.4 External Author Handoff")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        _ensure_external_and_handoff_ready(args.run_dir)
        # 素材池缺失或 stale 时先重建，使 readiness 的实质门看到最新素材池。
        ensure_material_pool_current(args.run_dir)
        readiness = writer_handoff_readiness(args.run_dir)
        if not readiness["ready"]:
            print(
                json.dumps(
                    {"status": "blocked", "reasons": readiness["reasons"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        receipt = build_writer_handoff(args.run_dir)
        mark_waiting_external_author(args.run_dir)
        print(
            json.dumps(
                {
                    "status": "WRITER_HANDOFF_READY",
                    "authoring_status": "waiting_external_author",
                    **receipt,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
