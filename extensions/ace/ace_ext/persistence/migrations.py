from __future__ import annotations

import time

from sqlalchemy import Column, Double, Integer, MetaData, String, Table, inspect, select, text

from ace_ext.governance import schema as governance_schema  # noqa: F401 - 注册迁移表
from ace_ext.persistence import agent_batches as batch_schema  # noqa: F401
from ace_ext.persistence import external_jobs as external_schema  # noqa: F401
from ace_ext.persistence import report_schema
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Database, Scope, base, event
from ace_ext.persistence.schema import metadata

VERSION = 7
MIGRATIONS = Table(
    "ace_df_schema_migrations",
    MetaData(),
    Column("version", Integer, primary_key=True),
    Column("name", String(160), nullable=False),
    mysql_engine="InnoDB",
)


def migrate(database: Database) -> int:
    """按版本应用独立 schema，不读写任何旧平台表；中断后可重复运行。"""
    with database.engine.connect() as connection:
        is_mysql = connection.dialect.name == "mysql"
        if is_mysql:
            acquired = connection.execute(
                text("SELECT GET_LOCK('ace_df_migration_v1', 20)")
            ).scalar()
            if acquired != 1:
                raise RuntimeError("迁移锁正被其他进程使用")
        try:
            MIGRATIONS.create(connection, checkfirst=True)
            versions = set(connection.execute(select(MIGRATIONS.c.version)).scalars())
            if 1 not in versions:
                metadata.create_all(connection)
                if is_mysql:
                    _repair_partial_v1(connection)
                connection.execute(MIGRATIONS.insert().values(version=1, name="durable_canvas"))
            if 2 not in versions:
                if is_mysql:
                    connection.execute(text("ALTER TABLE ace_df_schema_migrations ENGINE=InnoDB"))
                connection.execute(
                    MIGRATIONS.insert().values(version=2, name="transactional_migrations")
                )
            if 3 not in versions:
                _archive_legacy_config(connection)
                connection.execute(
                    MIGRATIONS.insert().values(version=3, name="archive_legacy_validation_payload")
                )
            if 4 not in versions:
                metadata.create_all(connection)
                connection.execute(MIGRATIONS.insert().values(version=4, name="teams_workspaces"))
            if 5 not in versions:
                metadata.create_all(connection)
                connection.execute(
                    MIGRATIONS.insert().values(version=5, name="durable_agent_batches")
                )
            if 6 not in versions:
                external_schema.jobs.create(connection, checkfirst=True)
                connection.execute(MIGRATIONS.insert().values(version=6, name="sgm_external_jobs"))
            if 7 not in versions:
                for table in (report_schema.datasets, report_schema.facts, report_schema.queries):
                    table.create(connection, checkfirst=True)
                connection.execute(MIGRATIONS.insert().values(version=7, name="warehouse_reports"))
            missing = set(metadata.tables) - set(inspect(connection).get_table_names())
            if missing:
                raise RuntimeError("业务 schema 不完整，请检查迁移记录")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if is_mysql:
                connection.execute(text("SELECT RELEASE_LOCK('ace_df_migration_v1')"))
    return VERSION


def _archive_legacy_config(connection) -> None:
    """旧配置已在历史图版本与导出档案中保存，编辑图不再重复传输验证记录。"""
    for row in connection.execute(select(s.projects)).mappings().all():
        graph = row["graph"]
        if not any("source_config" in node.get("config", {}) for node in graph["nodes"]):
            continue
        for node in graph["nodes"]:
            node.get("config", {}).pop("source_config", None)
        scope = Scope(row["tenant_id"], row["owner_id"])
        revision = row["revision"] + 1
        connection.execute(
            s.projects.update()
            .where(s.projects.c.id == row["id"])
            .values(graph=graph, revision=revision, updated_at=time.time())
        )
        connection.execute(
            s.graphs.insert().values(
                **base(scope, row["id"]), revision=revision, graph=graph, actor="migration:3"
            )
        )
        event(connection, scope, row["id"], "graph.legacy_archived", {"revision": revision})


def _repair_partial_v1(connection) -> None:
    # MySQL 默认存储引擎可能为 MyISAM，显式保证状态事务和亚秒租约精度。
    for table in metadata.tables.values():
        options = inspect(connection).get_table_options(table.name)
        if options.get("mysql_engine") != "InnoDB":
            connection.execute(text(f"ALTER TABLE `{table.name}` ENGINE=InnoDB"))
        columns = {column["name"]: column for column in inspect(connection).get_columns(table.name)}
        for column in table.columns:
            if (
                isinstance(column.type, Double)
                and str(columns[column.name]["type"]).upper() == "FLOAT"
            ):
                nullable = "NULL" if column.nullable else "NOT NULL"
                connection.execute(
                    text(f"ALTER TABLE `{table.name}` MODIFY `{column.name}` DOUBLE {nullable}")
                )
