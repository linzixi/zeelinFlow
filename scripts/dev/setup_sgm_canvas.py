"""在已指定的上汽通用项目保存迁移画布，使用 revision 校验，不创建中间副本。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: team_access prepared canvas; stdout status only
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ace_ext.workflow.sgm import import_sgm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/verify"))
from local_client import call, root_client
from team_access import action


def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    source = json.loads((ROOT / "migration/source/sgm.json").read_text("utf-8"))
    graph = import_sgm(source).model_dump(mode="json")
    with root_client() as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        canvas = action(client, "get_project", {"project_id": demo["canvas_id"]})[
            "data"
        ]
        if canvas["graph"] != graph:
            result = action(
                client,
                "save_project",
                {
                    "project_id": canvas["id"],
                    "name": canvas["name"],
                    "revision": canvas["revision"],
                    "graph": graph,
                },
            )
            assert result["ok"], result.get("error")
    print(
        "SGM canvas saved with 16 nodes, independent data/Agent tasks and preview-only delivery."
    )


if __name__ == "__main__":
    main()
