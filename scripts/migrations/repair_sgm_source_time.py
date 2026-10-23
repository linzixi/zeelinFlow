"""修复本次 SGM 验收窗口的源入库时间；仅新库目标画布，保留修订及备份。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes
Requires: no active canvas runs; CLI stdout counts only
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ace_ext.core.config import Settings
from ace_ext.core.contracts import Window
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.database import Database, Scope, event
from ace_ext.resources.sgm_source import source_time
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]


def main():
    proof = json.loads((ROOT / "output/verification/sgm-live.json").read_text("utf-8"))
    window = Window.model_validate(proof["window"])
    database = Database(
        Settings(_env_file=ROOT / ".env").database_url.get_secret_value()
    )
    changed = 0
    with database.transaction() as connection:
        project = (
            connection.execute(
                select(s.projects)
                .where(s.projects.c.id == proof["canvas_id"])
                .with_for_update()
            )
            .mappings()
            .one()
        )
        scope = Scope(project["tenant_id"], project["owner_id"])
        active = connection.execute(
            select(s.runs.c.id).where(
                s.runs.c.project_id == project["id"],
                s.runs.c.status.not_in(["succeeded", "failed", "cancelled"]),
            )
        ).first()
        assert active is None, "Wait for active runs before repairing timestamps"
        rows = [
            dict(row)
            for row in connection.execute(
                select(s.articles)
                .where(
                    s.articles.c.project_id == project["id"],
                    s.articles.c.mode == "live",
                )
                .with_for_update()
            ).mappings()
        ]
        backup = ROOT / ".runtime/sgm-before-time-repair.json"
        if not backup.exists():
            backup.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        for row in rows:
            corrected = source_time(row["data"].get("raw", {}).get("push_time"), None)
            assert corrected and window.start <= corrected < window.end
            if row["ingested_at"] == corrected.timestamp():
                continue
            row.update(
                data={**row["data"], "ingested_at": corrected.isoformat()},
                ingested_at=corrected.timestamp(),
                revision=row["revision"] + 1,
                updated_at=time.time(),
            )
            connection.execute(
                s.articles.update()
                .where(s.articles.c.id == row["id"])
                .values(
                    data=row["data"],
                    ingested_at=row["ingested_at"],
                    revision=row["revision"],
                    updated_at=row["updated_at"],
                )
            )
            ArticleRepository._history(
                connection,
                scope,
                row,
                "migration:sgm-source-time",
                "按保留原始 push_time 修复源入库时间",
            )
            changed += 1
        event(
            connection,
            scope,
            project["id"],
            "migration.source_time_repaired",
            {"count": changed, "run_id": proof["run_id"]},
        )
    database.close()
    print(f"Source timestamps repaired with audit: {changed}/{len(rows)}")


if __name__ == "__main__":
    main()
