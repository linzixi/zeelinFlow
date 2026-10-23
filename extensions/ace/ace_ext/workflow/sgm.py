from __future__ import annotations

from ace_ext.workflow.models import Bounds, Edge, Graph, Group, Node, Trigger

# Revision 209: media split and SIS precede type=2. The final node is preview-only.
STAGES = [
    ("data", "window", {}),
    ("data", "ingest", {"connector": "sgm"}),
    ("data", "persist", {"sgm_data": "normalize"}),
    ("data", "persist", {"sgm_data": "prepare"}),
    ("agent", "judge", {"sgm_stage": "sentiment"}),
    ("data", "content", {"sgm_data": "transcription"}),
    ("agent", "judge", {"sgm_stage": "problems"}),
    ("data", "persist", {"sgm_data": "mapping"}),
    ("data", "persist", {"sgm_data": "related"}),
    ("data", "persist", {"sgm_data": "policy"}),
    ("data", "persist", {"sgm_data": "checkpoint"}),
    ("data", "persist", {"sgm_data": "preview"}),
    ("data", "persist", {"sgm_data": "quality"}),
    ("data", "persist", {"sgm_data": "receipt", "auto_send": False, "preview_only": True}),
    ("data", "persist", {"sgm_data": "route"}),
    ("data", "persist", {"sgm_data": "branch"}),
]
LAYOUT = [
    (0, 0),
    (330, 0),
    (660, 0),
    (990, 0),
    (1650, 280),
    (1320, 280),
    (1650, 560),
    (1320, 560),
    (990, 560),
    (660, 560),
    (330, 560),
    (0, 560),
    (0, 840),
    (330, 840),
    (1320, 0),
    (1650, 0),
]


def import_sgm(source: dict) -> Graph:
    """Preserve source node IDs, edges, prompts and rules with independent executors."""
    nodes = []
    for index, (executor, operation, extra) in enumerate(STAGES):
        old = source["graph"]["nodes"][index]
        config = {
            k: v
            for k, v in old.get("config", {}).items()
            if k
            not in {
                "connectorBindings",
                "model_credential_ref",
                "max_tokens",
                "auth_ref",
                "credentialRef",
                "validationSuite",
            }
        }
        config.update(extra, source_revision=source["revision"], parity_version=1)
        if index == 0:
            config["closed_window_minutes"] = 5
        nodes.append(
            Node(
                id=old["id"],
                type=old["type"],
                title=old["title"],
                executor=executor,
                operation=operation,
                config=config,
                x=LAYOUT[index][0],
                y=LAYOUT[index][1],
                instructions=old.get("instructions", ""),
                skill=old.get("skill", ""),
                inputContract=old.get("inputContract", "ArticleBatch.v1"),
                outputContract=old.get("outputContract", "ArticleBatch.v1"),
                trigger=Trigger(lookbackMinutes=5),
            )
        )
    nodes[0].trigger = Trigger(
        kind="cron", cron="*/5 * * * *", enabled=False, mode="live", lookbackMinutes=5
    )
    nodes[13].title = "飞书发送与事务回写 · 本地预览"
    groups = []
    for title, indices in [
        ("01 采集与准入", [0, 1, 2, 3]),
        ("02 媒体分流与正文分析", [14, 15, 5, 4]),
        ("03 负面治理与卡片", [6, 7, 8, 9, 10, 11]),
        ("04 质量校验与预览回执", [12, 13]),
    ]:
        selected = [nodes[i] for i in indices]
        xmin, ymin = min(n.x for n in selected), min(n.y for n in selected)
        groups.append(
            Group(
                id=f"sgm-group-{len(groups)}",
                name=title,
                nodeIds=[n.id for n in selected],
                bounds=Bounds(
                    x=xmin - 24,
                    y=ymin - 56,
                    width=max(n.x for n in selected) - xmin + 296,
                    height=max(n.y for n in selected) - ymin + 192,
                ),
            )
        )
    return Graph(
        nodes=nodes, edges=[Edge.model_validate(e) for e in source["graph"]["edges"]], groups=groups
    )
