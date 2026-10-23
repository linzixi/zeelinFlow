"""只读导出旧 ACE 画布定义，过滤凭据，并保存原仓库变更基线。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: 旧 ACE .env 只读权限、PyMySQL、python-dotenv
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pymysql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT.parent / "ACE"
PROJECT = "proj_b33b4901cd79"
SECRET_KEY = re.compile(
    r"password|secret|token|api.?key|webhook|authorization", re.IGNORECASE
)


def clean(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(k): (
                "credential:configure-locally"
                if SECRET_KEY.search(str(k))
                else clean(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"https?://[^\s\"'<>]*(?:access_token|token|secret)=[^\s\"'<>]*",
            "credential:configure-locally",
            value,
            flags=re.IGNORECASE,
        )
    return value


def parse(value: object, default: object = None) -> object:
    return json.loads(value) if isinstance(value, str) and value else default


def rows(cursor, sql: str, *args: object) -> list[dict]:
    cursor.execute(sql, args)
    return list(cursor.fetchall())


def read_graph(cursor, tenant: int) -> dict:
    project = rows(
        cursor,
        "SELECT * FROM project WHERE tenant_id=%s AND code=%s AND deleted_at IS NULL",
        tenant,
        PROJECT,
    )[0]
    workflow = rows(
        cursor,
        "SELECT * FROM workflow WHERE project_id=%s "
        "AND deleted_at IS NULL ORDER BY (default_draft_id IS NOT NULL) DESC,id",
        project["id"],
    )[0]
    draft = workflow["default_draft_id"]
    nodes = []
    for row in rows(
        cursor,
        "SELECT * FROM workflow_draft_node WHERE workflow_draft_id=%s "
        "AND deleted_at IS NULL ORDER BY id",
        draft,
    ):
        node = {
            "id": row["node_key"],
            "type": row["node_type"],
            "title": row["title"],
            "x": float(row["position_x"] or 0),
            "y": float(row["position_y"] or 0),
            "instructions": row["instructions"] or "",
            "config": parse(row["config_json"], {}),
            "inputContract": row.get("input_contract_code") or "",
            "outputContract": row.get("output_contract_code") or "",
        }
        skill = rows(
            cursor,
            "SELECT v.instruction_content FROM project_node_binding b "
            "JOIN skill s ON s.id=b.resource_id JOIN skill_version v ON "
            "v.id=s.active_version_id WHERE b.workflow_draft_id=%s AND b.node_key=%s "
            "AND b.resource_type='SKILL' AND b.deleted_at IS NULL",
            draft,
            node["id"],
        )
        node["skill"] = skill[0]["instruction_content"] if skill else ""
        nodes.append(node)
    edges, groups = read_connections(cursor, draft)
    return {
        "sourceProjectId": PROJECT,
        "name": project["name"],
        "revision": project["revision"],
        "graph": {"nodes": nodes, "edges": edges, "groups": groups},
    }


def main() -> None:
    values = dotenv_values(SOURCE / ".env")
    connection = pymysql.connect(
        host=values["ACE_SGM_DB_HOST"],
        port=int(values.get("ACE_SGM_DB_PORT", "3306")),
        user=values["ACE_SGM_DB_USER"],
        password=values["ACE_SGM_DB_PASSWORD"],
        database=values["ACE_SGM_DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=8,
        read_timeout=15,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            connection.begin()
            graph = clean(
                read_graph(cursor, int(values.get("ACE_PLATFORM_TENANT_ID", "1")))
            )
    finally:
        connection.rollback()
        connection.close()
    output = ROOT / "migration" / "source"
    output.mkdir(parents=True, exist_ok=True)
    (output / "cmc-realtime.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, command in [
        ("status", ["status", "--porcelain=v1"]),
        ("diff", ["diff", "--binary"]),
    ]:
        result = subprocess.check_output(["git", "-C", str(SOURCE), *command])
        (output / f"legacy-{name}.sha256").write_text(
            hashlib.sha256(result).hexdigest(), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "project": PROJECT,
                "revision": graph["revision"],
                "nodes": [
                    {"id": n["id"], "type": n["type"], "title": n["title"]}
                    for n in graph["graph"]["nodes"]
                ],
            },
            ensure_ascii=False,
        )
    )


def read_connections(cursor, draft):
    edges = []
    for row in rows(
        cursor,
        "SELECT * FROM workflow_draft_edge WHERE workflow_draft_id=%s "
        "AND deleted_at IS NULL ORDER BY sort_order,id",
        draft,
    ):
        condition = parse(row.get("condition_json"), {})
        config = parse(row.get("edge_config_json"), {})
        edges.append(
            {
                "id": row["edge_key"],
                "source": row["source_node_key"],
                "target": row["target_node_key"],
                "label": row["label"] or "",
                "conditionKey": condition.get("key", ""),
                "conditionValue": condition.get("value", ""),
                "executionDisabled": config.get("executionDisabled", False),
            }
        )
    groups = []
    for row in rows(
        cursor,
        "SELECT * FROM workflow_draft_group WHERE workflow_draft_id=%s "
        "AND deleted_at IS NULL ORDER BY sort_order,id",
        draft,
    ):
        groups.append(
            {
                "id": row["group_key"],
                "name": row["name"],
                "color": row["color"],
                "nodeIds": parse(row.get("style_json"), {}).get("nodeIds", []),
                "bounds": {
                    key: float(row[col] or 0)
                    for key, col in [
                        ("x", "position_x"),
                        ("y", "position_y"),
                        ("width", "width"),
                        ("height", "height"),
                    ]
                },
            }
        )
    return edges, groups


if __name__ == "__main__":
    main()
