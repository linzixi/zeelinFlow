"""读取一个完整真实窗口并保存本地诊断，输出覆盖率与字段名，不发送消息。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: SQTY credentials; stdout has no signatures or credentials
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ace_ext.core.config import Settings
from ace_ext.core.contracts import Window
from ace_ext.resources.sgm_source import SgmSource

ROOT = Path(__file__).resolve().parents[2]


def main():
    settings = Settings(_env_file=ROOT / ".env")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    end = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
    for minutes in (5, 30, 120):
        window = Window(start=end - timedelta(minutes=minutes), end=end)
        records, coverage = SgmSource(settings).fetch({}, window)
        if records:
            break
    (ROOT / ".runtime/sgm-source.json").write_text(
        json.dumps(
            {
                "coverage": coverage,
                "records": [row.model_dump(mode="json") for row in records],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"coverage": coverage, "fields": list(records[0].raw) if records else []},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
