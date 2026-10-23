"""单独复核真实报告节点，不重新取数/打标，不创建画布副本。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes (fixed replay key)
Requires: succeeded main SGM run and running Gateway; stdout status only
"""

from __future__ import annotations

import json
import sys

from local_client import ROOT, root_client
from team_access import action


def main():
    main_run = json.loads(
        (ROOT / "output/verification/sgm-parity-live.json").read_text("utf-8")
    )
    path = ROOT / "output/verification/sgm-report-final.json"
    canvas = main_run["canvas_id"]
    with root_client() as client:
        if "--start" in sys.argv:
            detail = action(
                client,
                "run_detail",
                {"project_id": canvas, "run_id": main_run["run_id"]},
            )["data"]
            task = next(
                t for t in detail["tasks"] if t["node"]["type"] == "warehouse_report"
            )
            result = action(
                client,
                "replay_task",
                {
                    "project_id": canvas,
                    "task_id": task["id"],
                    "key": "sgm-report-transcription-scope-v1",
                    "downstream": False,
                },
            )
            assert result["ok"], result.get("error")
            run_id = result["data"]["id"]
        else:
            run_id = json.loads(path.read_text("utf-8"))["run_id"]
        detail = action(client, "run_detail", {"project_id": canvas, "run_id": run_id})[
            "data"
        ]
        result = {
            "run_id": run_id,
            "source_run_id": main_run["run_id"],
            "canvas_id": canvas,
            "status": detail["status"],
            "tasks": [
                {
                    k: t[k]
                    for k in (
                        "id",
                        "status",
                        "error",
                        "thread_id",
                        "input_snapshot_id",
                        "output_snapshot_id",
                    )
                }
                for t in detail["tasks"]
            ],
        }
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
