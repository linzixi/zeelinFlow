from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ace_ext.core.contracts import Window
from ace_ext.core.errors import DeferUntil, LeaseLost, Unavailable
from ace_ext.persistence import external_jobs
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.sgm import transcription as service


def start_task(database, scope, saved_project):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    now = datetime.now(UTC)
    repo.launch(
        scope,
        saved_project["id"],
        origin="manual",
        mode="live",
        key="sis",
        window=Window(start=now - timedelta(minutes=5), end=now),
        start="fetch",
        single=True,
    )
    return repo.claim("data", lease_seconds=90)


def test_sis_durable_download_asr_resume_and_lease_fence(
    database, scope, saved_project, monkeypatch
):
    task = start_task(database, scope, saved_project)
    row = {
        "id": "video",
        "url": "https://example.com/v",
        "content": "源文字",
        "raw": {"news_video_urls": ["https://example.com/v.mp4"]},
    }
    settings = SimpleNamespace(
        sgm_sis_enabled=True,
        sgm_sis_timeout_minutes=60,
        sgm_sis_poll_seconds=15,
        sgm_sis_project_id="test",
        sgm_asr_url="https://example.com/asr",
    )
    calls = []
    monkeypatch.setattr(service, "db_config", lambda _: None)
    monkeypatch.setattr(service, "asr_auth", lambda _: {})
    monkeypatch.setattr(service.sis, "submit_task", lambda *args: calls.append("download"))
    monkeypatch.setattr(
        service.sis,
        "read_task_result",
        lambda *args: SimpleNamespace(
            completed=False, state="pending", media_url="https://example.com/download.mp4"
        ),
    )
    monkeypatch.setattr(
        service.asr, "submit_asr_job", lambda *args, **kwargs: calls.append("asr") or "external-1"
    )
    monkeypatch.setattr(
        service.asr,
        "read_asr_job",
        lambda *args, **kwargs: SimpleNamespace(
            state="completed", transcript="真实转写结果", segments=[]
        ),
    )
    with pytest.raises(DeferUntil):
        service.execute(database, settings, task, [row])
    with pytest.raises(DeferUntil):
        service.execute(database, settings, task, [row])
    result = service.execute(database, settings, task, [row])[0]
    assert result["sis_status"] == "succeeded" and result["source_content"] == "源文字"
    assert result["content"] == "真实转写结果" and result["asr_job_id"] == "external-1"
    assert service.execute(database, settings, task, [row])[0] == result
    assert calls == ["download", "asr"]
    job = external_jobs.prepare(database, task, row)
    with pytest.raises(LeaseLost):
        external_jobs.save(database, {**task, "lease_token": "stale"}, job, "completed")


def test_ambiguous_asr_submission_never_reposts(database, scope, saved_project, monkeypatch):
    task = start_task(database, scope, saved_project)
    row = {"id": "v", "url": "https://example.com/v"}
    job = external_jobs.prepare(database, task, row)
    external_jobs.save(database, task, job, "asr_submitting")
    monkeypatch.setattr(service, "advance", lambda *args: pytest.fail("重复提交"))
    with pytest.raises(Unavailable, match="停止重复提交"):
        service.tick(database, None, task, row)


def test_failure_policy_skip_is_distinct_from_source_fallback(monkeypatch):
    monkeypatch.setattr(service, "tick", lambda *args: {"id": "v", "sis_status": "fallback_source"})
    settings = SimpleNamespace(sgm_sis_enabled=True)
    task = {"node": {"config": {"asr_failure_policy": "skip"}}}
    assert service.execute(None, settings, task, [{}])[0]["assessment_status"] == "skipped"
    task["node"]["config"]["asr_failure_policy"] = "fail"
    with pytest.raises(Unavailable):
        service.execute(None, settings, task, [{}])
