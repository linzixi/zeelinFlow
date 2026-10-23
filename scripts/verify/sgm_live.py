"""启动/观察上汽通用真实完整窗口，保存可审计结果，不调用任何发送接口。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes (same source window reuses run)
Requires: installed SGM canvas and running Gateway; stdout status only
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from local_client import ROOT, call, root_client
from team_access import action


def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    source = json.loads((ROOT / ".runtime/sgm-source.json").read_text("utf-8"))
    window = source["coverage"][0]["window"]
    canvas = demo["canvas_id"]
    path = ROOT / "output/verification/sgm-live.json"
    with root_client() as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        if "--start" in sys.argv:
            result = action(
                client,
                "run",
                {
                    "project_id": canvas,
                    "mode": "live",
                    "end": window["end"],
                    "lookback_minutes": 5,
                    "key": "sgm-live:" + window["end"],
                },
            )
            assert result["ok"], result.get("error")
            run_id = result["data"]["id"]
        else:
            run_id = json.loads(path.read_text("utf-8"))["run_id"]
        detail = action(client, "run_detail", {"project_id": canvas, "run_id": run_id})[
            "data"
        ]
        articles = action(
            client,
            "list_articles",
            {"project_id": canvas, "limit": 200, "mode": "live"},
        )["data"]
        write_report(path, run_id, canvas, window, detail, articles)


def write_report(path, run_id, canvas, window, detail, articles):
    report = {
        "run_id": run_id,
        "canvas_id": canvas,
        "real_source": True,
        "external_delivery": False,
        "window": window,
        "status": detail["status"],
        "task_counts": dict(Counter(t["status"] for t in detail["tasks"])),
        "tasks": [
            {
                k: t[k]
                for k in (
                    "id",
                    "node_id",
                    "status",
                    "thread_id",
                    "agent_run_id",
                    "input_snapshot_id",
                    "output_snapshot_id",
                    "error",
                )
            }
            for t in detail["tasks"]
        ],
        "article_count": articles["total"],
        "sentiments": dict(
            Counter(r["data"].get("sentiment") for r in articles["items"])
        ),
        "assessment": dict(
            Counter(r["data"].get("assessment_status") for r in articles["items"])
        ),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "run_id",
                    "status",
                    "task_counts",
                    "article_count",
                    "sentiments",
                    "assessment",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
