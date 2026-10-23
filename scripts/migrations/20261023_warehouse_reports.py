"""执行 v7 冻结数仓、问数事实表与查询审计迁移及其依赖版本；仅输出版本号，不输出连接凭据。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes
Requires: PYTHONPATH=extensions/ace, root .env, local database
"""

from __future__ import annotations

from pathlib import Path

from ace_ext.core.config import Settings
from ace_ext.persistence.database import Database
from ace_ext.persistence.migrations import migrate


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = Settings(_env_file=root / ".env")
    database = Database(settings.database_url.get_secret_value())
    try:
        print(f"ACE schema version: {migrate(database)}")
    finally:
        database.close()


if __name__ == "__main__":
    main()
