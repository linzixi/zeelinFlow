"""只读导出上汽通用原画布，保留既有仓库基线并复用脱敏处理。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: old ACE environment; stdout node names only
"""

from __future__ import annotations

import json

import export_ace_project as source
import pymysql
from dotenv import dotenv_values, set_key


def main() -> None:
    values = dotenv_values(source.SOURCE / ".env")
    local = dotenv_values(source.ROOT / ".env")
    for name in ("SQTY_APP_ID", "SQTY_APP_SECRET"):
        if not local.get(name) and values.get(name):
            set_key(source.ROOT / ".env", name, values[name])
    source.PROJECT = "proj_e67b65830e37"
    connection = pymysql.connect(
        host=values["ACE_SGM_DB_HOST"],
        port=int(values.get("ACE_SGM_DB_PORT", 3306)),
        user=values["ACE_SGM_DB_USER"],
        password=values["ACE_SGM_DB_PASSWORD"],
        database=values["ACE_SGM_DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=8,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            connection.begin()
            graph = source.clean(
                source.read_graph(cursor, int(values.get("ACE_PLATFORM_TENANT_ID", 1)))
            )
    finally:
        connection.rollback()
        connection.close()
    (source.ROOT / "migration/source/sgm.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "revision": graph["revision"],
                "nodes": [
                    {"id": node["id"], "type": node["type"], "title": node["title"]}
                    for node in graph["graph"]["nodes"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
