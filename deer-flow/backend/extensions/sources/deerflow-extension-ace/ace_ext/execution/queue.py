from __future__ import annotations

import time

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from ace_ext.core.config import Settings
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Database


class QueueNotifications:
    """Redis 仅承载可重复通知，MySQL 的租约领取决定谁实际执行。"""

    def __init__(self, database: Database, settings: Settings):
        self.db, self.settings = database, settings
        self.redis = Redis.from_url(
            settings.redis_conn_string.get_secret_value(),
            protocol=2,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def publish(self, limit: int = 100) -> int:
        if not self.settings.cache_enabled:
            return 0
        with self.db.transaction() as connection:
            rows = (
                connection.execute(
                    select(s.outbox)
                    .where(
                        s.outbox.c.tenant_id == self.settings.ace_df_tenant,
                        s.outbox.c.published_at.is_(None),
                    )
                    .order_by(s.outbox.c.created_at)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        published = 0
        for row in rows:
            key = f"{self.settings.queue_prefix}:{row['executor']}"
            try:
                with self.redis.pipeline() as pipeline:
                    pipeline.rpush(key, row["task_id"])
                    pipeline.ltrim(key, -4096, -1)
                    pipeline.execute()
            except RedisError:
                # 队列断线不会清除 Outbox；Worker 的数据库扫描仍然可执行。
                return published
            with self.db.transaction() as connection:
                connection.execute(
                    s.outbox.update()
                    .where(s.outbox.c.id == row["id"])
                    .values(
                        published_at=time.time(), publish_attempts=s.outbox.c.publish_attempts + 1
                    )
                )
            published += 1
        return published

    def consume(self, executor: str) -> bool:
        if not self.settings.cache_enabled:
            return False
        try:
            return bool(self.redis.lpop(f"{self.settings.queue_prefix}:{executor}"))
        except RedisError:
            return False

    def health(self) -> bool:
        if not self.settings.cache_enabled:
            return False
        try:
            return bool(self.redis.ping())
        except RedisError:
            return False

    def close(self) -> None:
        self.redis.close()
