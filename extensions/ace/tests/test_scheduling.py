from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ace_ext.persistence import schema as s
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.persistence.schedules import ScheduleRepository
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.workflow.models import Trigger
from ace_ext.workflow.scheduling import delivery_policy, next_occurrence
from ace_ext.workflow.validation import reachable

TIMES = ["08:30", "10:30", "12:30", "14:30", "16:30", "18:30"]


def test_fixed_times_do_not_drift_on_save_and_weekly_monthly_supported():
    trigger = Trigger(kind="cron", runAtTimes=TIMES)
    reference = datetime.fromisoformat("2026-10-22T17:42:00+08:00")
    assert next_occurrence(trigger, reference).isoformat() == "2026-10-22T18:30:00+08:00"
    assert next_occurrence(Trigger(kind="cron", cron="30 9 * * 1"), reference).weekday() == 0
    assert next_occurrence(Trigger(kind="cron", cron="0 9 1 * *"), reference).day == 1


def test_delivery_limits_keep_manual_exception_and_block_replays():
    before = datetime.fromisoformat("2026-10-22T08:55:00+08:00")
    for origin, mode, allowed in [
        ("scheduled", "live", False),
        ("manual", "live", True),
        ("manual", "simulation", False),
        ("replay", "live", False),
    ]:
        assert (
            delivery_policy(origin=origin, mode=mode, now=before, window_end=before)[0] == allowed
        )
    end = before.replace(hour=20)
    assert not delivery_policy(origin="scheduled", mode="live", now=end, window_end=end)[0]


def test_due_occurrence_is_idempotent(database, scope, graph):
    graph.nodes[0].trigger = Trigger(kind="cron", enabled=True, runAtTimes=TIMES)
    saved = ProjectRepository(database).create(scope, "定时验证", graph)
    with database.transaction() as connection:
        schedule = (
            connection.execute(select(s.schedules).where(s.schedules.c.project_id == saved["id"]))
            .mappings()
            .one()
        )
    repo = ScheduleRepository(database, scope.tenant_id)
    due = datetime.fromtimestamp(schedule["next_at"], UTC)
    assert len(repo.dispatch_due(due)) == 1
    assert repo.dispatch_due(due) == []


def test_data_event_does_not_launch_an_independent_report_schedule(graph):
    graph.nodes[1].trigger = Trigger(kind="cron", cron="0 9 1 * *", mode="live")
    assert reachable(graph, "fetch") == {"fetch", "metrics"}
    assert reachable(graph, "judge") == {"judge"}


def test_disabling_scheduled_node_updates_persisted_trigger(database, scope, graph):
    graph.nodes[0].trigger = Trigger(kind="cron", enabled=True, cron="0 9 * * *", mode="live")
    repo = ProjectRepository(database)
    saved = repo.create(scope, "定时停用", graph)
    graph.nodes[0].enabled = False
    repo.save(scope, saved["id"], graph, 1)
    with database.transaction() as connection:
        row = (
            connection.execute(select(s.schedules).where(s.schedules.c.project_id == saved["id"]))
            .mappings()
            .one()
        )
    assert row["mode"] == "live" and not row["enabled"]


def test_independent_node_clocks_and_title_save_preserve_next_occurrence(database, scope, graph):
    graph.nodes[0].trigger = Trigger(
        kind="cron", enabled=True, cron="*/5 * * * *", lookbackMinutes=5
    )
    graph.nodes[1].trigger = Trigger(
        kind="cron", enabled=True, cron="*/10 * * * *", lookbackMinutes=60
    )
    projects = ProjectRepository(database)
    saved = projects.create(scope, "节点独立时钟", graph)
    due = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    with database.transaction() as connection:
        for node_id, at in [("fetch", due), ("judge", due + timedelta(minutes=5))]:
            connection.execute(
                s.schedules.update()
                .where(
                    s.schedules.c.project_id == saved["id"],
                    s.schedules.c.node_id == node_id,
                )
                .values(next_at=at.timestamp())
            )
    graph.nodes[0].title = "仅改标题"
    projects.save(scope, saved["id"], graph, saved["revision"])
    schedules = ScheduleRepository(database, scope.tenant_id)
    tasks = TaskRepository(database, tenant_id=scope.tenant_id)
    first = schedules.dispatch_due(due)
    assert len(first) == 1
    detail = tasks.detail(scope, saved["id"], first[0])
    assert {task["node_id"] for task in detail["tasks"]} == {"fetch", "metrics"}
    assert datetime.fromisoformat(detail["window"]["start"]) == due - timedelta(minutes=5)
    later = schedules.dispatch_due(due + timedelta(minutes=5))
    details = [tasks.detail(scope, saved["id"], run_id) for run_id in later]
    independent = next(
        item for item in details if {task["node_id"] for task in item["tasks"]} == {"judge"}
    )
    assert datetime.fromisoformat(independent["window"]["start"]) == due - timedelta(minutes=55)
    assert schedules.dispatch_due(due + timedelta(minutes=5)) == []
