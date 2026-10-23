"""从已落库真实文章执行媒体分流及后续，保留首轮证明，不重复取数/情感。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes (fixed verification key)
Requires: corrected source times, running Gateway; stdout counts only
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from local_client import ROOT, call, root_client
from team_access import action


def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    original = json.loads(
        (ROOT / "output/verification/sgm-live.json").read_text("utf-8")
    )
    policy = "--policy" in sys.argv
    path = ROOT / f"output/verification/sgm-{'policy' if policy else 'finalize'}.json"
    with root_client() as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        if "--start" in sys.argv:
            graph = action(client, "get_project", {"project_id": demo["canvas_id"]})[
                "data"
            ]["graph"]
            node = next(
                n
                for n in graph["nodes"]
                if n["config"].get("sgm_data") == ("policy" if policy else "route")
            )
            response = action(
                client,
                "run",
                {
                    "project_id": demo["canvas_id"],
                    "mode": "live",
                    "end": original["window"]["end"],
                    "lookback_minutes": 5,
                    "key": "sgm-evidence-policy-v1"
                    if policy
                    else "sgm-source-fallback-final-v1",
                    "start": node["id"],
                    "single": False,
                },
            )
            assert response["ok"], response.get("error")
            run_id = response["data"]["id"]
        else:
            run_id = json.loads(path.read_text("utf-8"))["id"]
        detail = action(
            client, "run_detail", {"project_id": demo["canvas_id"], "run_id": run_id}
        )["data"]
        path.write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "id": run_id,
                    "status": detail["status"],
                    "tasks": dict(Counter(t["status"] for t in detail["tasks"])),
                    "errors": [t["error"] for t in detail["tasks"] if t["error"]],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
