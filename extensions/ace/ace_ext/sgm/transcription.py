from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from ace_ext.core.errors import DeferUntil, Unavailable
from ace_ext.persistence import external_jobs as state
from ace_ext.vendor.legacy_sgm import huawei_asr as asr
from ace_ext.vendor.legacy_sgm import sis


def db_config(settings):
    return sis.SgmSisDatabaseConfig(
        host=settings.sgm_sis_db_host,
        port=settings.sgm_sis_db_port,
        user=settings.sgm_sis_db_user,
        password=settings.sgm_sis_db_password.get_secret_value(),
        database=settings.sgm_sis_db_name,
    )


def asr_auth(settings):
    return {
        "access_key": settings.sgm_asr_access_key.get_secret_value(),
        "secret_key": settings.sgm_asr_secret_key.get_secret_value(),
    }


def tick(database, settings, task, article):
    job = state.prepare(database, task, article)
    if job["state"] in {"completed", "fallback"}:
        return result(article, job)
    if job["state"] == "asr_submitting":
        # A crash after non-idempotent ASR admission is ambiguous; never issue a duplicate POST.
        raise Unavailable("ASR 提交回执尚未落库，请核对外部任务后恢复，已停止重复提交")
    timeout = int(
        task["node"]["config"].get("sis_timeout_minutes", settings.sgm_sis_timeout_minutes)
    )
    if time.time() - job["data"]["began_at"] >= timeout * 60:
        state.save(database, task, job, "fallback", error="sis-timeout", terminal="timed_out")
    else:
        try:
            advance(database, settings, task, article, job)
        except (sis.SgmSisError, asr.SgmHuaweiAsrError) as exc:
            if job["state"] == "asr_submitting":
                raise Unavailable(
                    "ASR 提交状态不确定，已保留提交意图，请核对外部回执后恢复"
                ) from exc
            errors = job["data"].get("errors", 0) + 1
            # The public error is deliberately bounded; provider URLs/credentials stay private.
            state.save(
                database,
                task,
                job,
                "fallback" if errors >= 3 else "retry",
                errors=errors,
                error=type(exc).__name__,
                resume_state=job["state"],
                terminal="max_attempts" if errors >= 3 else "",
            )
    return result(article, job) if job["state"] in {"completed", "fallback"} else None


def advance(database, settings, task, article, job):
    current = job["data"].get("resume_state", "queued") if job["state"] == "retry" else job["state"]
    if current == "queued":
        remote = sis.build_task_payload(
            project_id=settings.sgm_sis_project_id,
            article_id=f"deerflow:{task['project_id']}:{article['id']}",
            news_url=article["url"],
            news_posttime=article.get("raw", {}).get("news_posttime"),
            news_video_urls=article.get("raw", {}).get("news_video_urls"),
        )
        sis.submit_task(db_config(settings), remote)
        state.save(database, task, job, "downloading", correlation=remote["news_uuid"])
        return
    observed = sis.read_task_result(db_config(settings), job["data"]["correlation"])
    if observed.completed and observed.content:
        state.save(
            database,
            task,
            job,
            "completed",
            transcript=observed.content,
            transcript_sha256=hashlib.sha256(observed.content.encode()).hexdigest(),
        )
        return
    if current == "asr_pending":
        transcript = asr.read_asr_job(
            settings.sgm_asr_url, job["data"]["asr_job_id"], **asr_auth(settings)
        )
        if transcript.state == "completed":
            state.save(
                database,
                task,
                job,
                "completed",
                transcript=transcript.transcript,
                segments=list(transcript.segments),
                transcript_sha256=hashlib.sha256(transcript.transcript.encode()).hexdigest(),
            )
        elif transcript.state in {"failed", "no_transcript"}:
            state.save(
                database, task, job, "fallback", error=transcript.reason, terminal=transcript.state
            )
    elif observed.media_url and settings.sgm_asr_url:
        state.save(database, task, job, "asr_submitting")
        job_id = asr.submit_asr_job(settings.sgm_asr_url, observed.media_url, **asr_auth(settings))
        state.save(database, task, job, "asr_pending", asr_job_id=job_id)
    elif observed.state == "failed":
        state.save(
            database,
            task,
            job,
            "fallback",
            terminal="download_failed",
            error=f"sis-terminal-status:{observed.status}",
        )


def result(article, job):
    record = dict(article)
    record.update(
        sis_job_id=job["id"],
        sis_correlation=job["data"].get("correlation", ""),
        asr_job_id=job["data"].get("asr_job_id", ""),
        source_content=article.get("source_content", article.get("content", "")),
    )
    if job["state"] == "completed":
        record.update(
            content=job["data"]["transcript"],
            transcript=job["data"]["transcript"],
            sis_status="succeeded",
            evidence_limit="",
            content_status="transcribed",
        )
    else:
        record.update(
            sis_status="fallback_source",
            content_status="source_fallback",
            evidence_limit="视频转写终态："
            + job["data"].get("error", "unknown")
            + "；仅使用源标题正文",
        )
    return record


def execute(database, settings, task, records):
    if not records:
        return []
    if not settings.sgm_sis_enabled:
        raise Unavailable("SGM 视频节点尚未启用 SIS，请配置后恢复任务")
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="sgm-sis") as pool:
        results = list(pool.map(lambda row: tick(database, settings, task, row), records))
    if any(row is None for row in results):
        raise DeferUntil(
            time.time() + settings.sgm_sis_poll_seconds,
            "视频下载/转写处理中，任务已入库并释放队列执行槽",
        )
    policy = task["node"]["config"].get("asr_failure_policy", "fallback-to-source")
    if policy == "fail" and any(row.get("sis_status") == "fallback_source" for row in results):
        raise Unavailable("视频转写失败，当前节点策略禁止降级")
    if policy == "skip":
        return [
            {**row, "skip_reason": "视频转写失败，节点配置为跳过", "assessment_status": "skipped"}
            if row.get("sis_status") == "fallback_source"
            else row
            for row in results
        ]
    return results
