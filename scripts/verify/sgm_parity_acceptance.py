"""核验本轮 SGM 原流程与真实问数报告，导出本地证据；不发送消息。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes (read-only database and API, replaces local evidence)
Requires: succeeded sgm-parity-live.json run; stdout aggregates only
"""

from __future__ import annotations

import base64
import json
from collections import Counter

from ace_ext.core.config import Settings
from ace_ext.persistence import external_jobs, report_schema
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Database
from local_client import ROOT, call, login, root_client
from sqlalchemy import select
from team_access import action


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_run(database, run_id):
    with database.transaction() as connection:
        run = dict(
            connection.execute(select(s.runs).where(s.runs.c.id == run_id))
            .mappings()
            .one()
        )
        tasks = [
            dict(t)
            for t in connection.execute(
                select(s.tasks).where(s.tasks.c.run_id == run_id)
            ).mappings()
        ]
        assert run["status"] == "succeeded" and len(tasks) == 17
        assert all(t["status"] == "succeeded" for t in tasks)
        outputs = {
            t["node_id"]: connection.execute(
                select(s.snapshots.c.payload).where(
                    s.snapshots.c.id == t["output_snapshot_id"]
                )
            ).scalar_one()
            for t in tasks
        }
        articles = [
            dict(a)
            for a in connection.execute(
                select(s.articles).where(
                    s.articles.c.project_id == run["project_id"],
                    s.articles.c.deleted_at.is_(None),
                    s.articles.c.mode == "live",
                )
            ).mappings()
        ]
        events = [
            dict(e)
            for e in connection.execute(
                select(s.events).where(s.events.c.run_id == run_id)
            ).mappings()
        ]
        jobs = [
            dict(j)
            for j in connection.execute(
                select(external_jobs.jobs).where(
                    external_jobs.jobs.c.task_id.in_([t["id"] for t in tasks])
                )
            ).mappings()
        ]
    return run, tasks, outputs, articles, events, jobs


def verify_flow(run, tasks, outputs, articles, events, jobs):
    source = json.loads((ROOT / "migration/source/sgm.json").read_text("utf-8"))
    original_ids = [n["id"] for n in source["graph"]["nodes"]]
    assert [n["id"] for n in run["graph"]["nodes"][:16]] == original_ids
    assert run["graph"]["edges"][:16] == source["graph"]["edges"]
    coverage = outputs[original_ids[1]]["context"]["coverage"]
    assert all(
        c["complete"] and c["total"] == c["fetched"] == c["unique"] for c in coverage
    )
    input_ids = {r["id"] for r in outputs[original_ids[3]]["records"]}
    judged = outputs[original_ids[4]]["records"]
    skipped = [r for r in outputs[original_ids[3]]["records"] if r.get("skip_reason")]
    assert input_ids == {r["id"] for r in judged} | {r["id"] for r in skipped}
    negatives = {r["id"] for r in judged if r["sentiment"] == "negative"}
    extracted = outputs[original_ids[6]]["records"]
    assert negatives == {r["id"] for r in extracted}
    assert not any(e["kind"] == "article.analysis_stale" for e in events)
    assert not any(a["data"].get("delivered") for a in articles)
    edited = next(a for a in articles if a["id"] == "d4b7d29e6fea44fcbd7f997a0debaa3a")
    assert edited["review_status"] == "watching"
    assert edited["data"]["problem_content"] == "尾门无法关闭（依据现有文字）"
    receipt = next(
        a
        for a in outputs[original_ids[13]]["artifacts"]
        if a["name"] == "sgm-preview-receipt.json"
    )
    receipt = json.loads(receipt["content"])
    assert receipt["external_messages_sent"] == 0
    assert all(
        not i["delivered"] and i["feishu_push_status"] == 0 for i in receipt["items"]
    )
    return {
        "source_revision": 209,
        "canvas_revision": run["graph_revision"],
        "coverage": coverage,
        "input": len(input_ids),
        "judged": len(judged),
        "skipped": len(skipped),
        "skip_reasons": dict(Counter(r["skip_reason"] for r in skipped)),
        "sentiments": dict(Counter(a["data"].get("sentiment") for a in articles)),
        "type3_articles": len(extracted),
        "extraction_status": dict(
            Counter(r.get("extraction_status") for r in extracted)
        ),
        "video_jobs": len(jobs),
        "video_states": dict(Counter(j["state"] for j in jobs)),
        "video_fallback_reasons": dict(
            Counter(
                j["data"].get("terminal", "unknown")
                for j in jobs
                if j["state"] == "fallback"
            )
        ),
        "preview_cards": sum(i["would_send"] for i in receipt["items"]),
        "external_messages_sent": 0,
        "manual_override_preserved": True,
        "stale_analysis_events": 0,
    }


def export_artifacts(outputs, destination):
    destination.mkdir(parents=True, exist_ok=True)
    names = []
    for output in outputs.values():
        for artifact in output.get("artifacts", []):
            name = artifact["name"]
            assert "/" not in name and "\\" not in name and ".." not in name
            path = destination / name
            if artifact.get("content_base64"):
                path.write_bytes(base64.b64decode(artifact["content_base64"]))
            else:
                path.write_text(artifact["content"], encoding="utf-8")
            names.append(name)
    return sorted(set(names))


def verify_report(database, tasks):
    task = next(t for t in tasks if t["node"]["type"] == "warehouse_report")
    with database.transaction() as connection:
        dataset = dict(
            connection.execute(
                select(report_schema.datasets).where(
                    report_schema.datasets.c.task_id == task["id"]
                )
            )
            .mappings()
            .one()
        )
        audits = [
            dict(a)
            for a in connection.execute(
                select(report_schema.queries).where(
                    report_schema.queries.c.dataset_id == dataset["id"],
                    report_schema.queries.c.thread_id == task["thread_id"],
                )
            ).mappings()
        ]
    assert dataset["row_count"] == 111
    with root_client() as client:
        state = call(client, "GET", f"/api/threads/{task['thread_id']}/state")
        messages = state.get("values", {}).get("messages", [])
        tool_calls = [
            m
            for m in messages
            if m.get("type") == "tool" and "warehouse_query" in m.get("name", "")
        ]
        assert len(tool_calls) >= 6 and len(audits) >= 6
    return {
        "dataset_id": dataset["id"],
        "run_id": task["run_id"],
        "output_snapshot_id": task["output_snapshot_id"],
        "snapshot_id": dataset["snapshot_id"],
        "row_count": dataset["row_count"],
        "queries": len(audits),
        "query_ids": [a["id"] for a in audits],
        "actual_tool_results": len(tool_calls),
        "thread_id": task["thread_id"],
        "agent_run_id": task["agent_run_id"],
    }


def verify_reviewer(canvas, articles):
    accounts = json.loads(
        (ROOT / ".runtime/team-demo-accounts.json").read_text("utf-8")
    )
    with login(accounts["reviewer"]) as client:
        rows = action(client, "list_articles", {"project_id": canvas, "limit": 200})[
            "data"
        ]
        assert all(
            r["data"].get("decision") in ("report", "review") for r in rows["items"]
        )
        for name in ("get_project", "list_runs"):
            denied = action(client, name, {"project_id": canvas})
            assert not denied["ok"] and denied["error"]["code"] == "forbidden"
        ordinary = next(a for a in articles if a["data"].get("decision") == "observe")
        denied = action(
            client,
            "article_history",
            {"project_id": canvas, "article_id": ordinary["id"]},
        )
        assert not denied["ok"] and denied["error"]["code"] == "forbidden"
    return {
        "reviewable_articles": rows["total"],
        "canvas_and_runs_denied": True,
        "ordinary_article_denied": True,
    }


def main():
    current = json.loads(
        (ROOT / "output/verification/sgm-parity-live.json").read_text("utf-8")
    )
    database = Database(
        Settings(_env_file=ROOT / ".env").database_url.get_secret_value()
    )
    run, tasks, outputs, articles, events, jobs = load_run(database, current["run_id"])
    report_tasks = final_report(database, tasks, outputs)
    result = {
        "passed": True,
        "run_id": run["id"],
        "canvas_id": run["project_id"],
        "flow": verify_flow(run, tasks, outputs, articles, events, jobs),
        "report": verify_report(database, report_tasks),
        "access": verify_reviewer(run["project_id"], articles),
    }
    result["artifacts"] = export_artifacts(outputs, ROOT / "output/sgm-report")
    result["nodes"] = [
        {
            "id": t["node_id"],
            "title": t["node"]["title"],
            "status": t["status"],
            "input_snapshot_id": t["input_snapshot_id"],
            "output_snapshot_id": t["output_snapshot_id"],
            "records": len(outputs[t["node_id"]]["records"]),
        }
        for t in tasks
    ]
    save(ROOT / "output/verification/sgm-parity-acceptance.json", result)
    print(
        json.dumps(
            {k: result[k] for k in ("passed", "run_id", "flow", "report", "access")},
            ensure_ascii=False,
        )
    )


def final_report(database, tasks, outputs):
    path = ROOT / "output/verification/sgm-report-final.json"
    if not path.exists():
        return tasks
    report = json.loads(path.read_text("utf-8"))
    assert report["source_run_id"] == tasks[0]["run_id"]
    with database.transaction() as connection:
        rows = [
            dict(t)
            for t in connection.execute(
                select(s.tasks).where(s.tasks.c.run_id == report["run_id"])
            ).mappings()
        ]
        assert len(rows) == 1 and rows[0]["status"] == "succeeded"
        outputs[rows[0]["node_id"]] = connection.execute(
            select(s.snapshots.c.payload).where(
                s.snapshots.c.id == rows[0]["output_snapshot_id"]
            )
        ).scalar_one()
    return rows


if __name__ == "__main__":
    main()
