"""固定旧 ACE 的纯 ES 协议实现，保留来源哈希；不导入旧框架或修改旧仓库。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: read-only legacy integrations sources
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source = root.parent / "ACE" / "agent_framework" / "integrations"
    destination = root / "extensions" / "ace" / "ace_ext" / "vendor" / "legacy_es"
    destination.mkdir(parents=True, exist_ok=True)
    (destination.parent / "__init__.py").touch()
    (destination / "__init__.py").touch()
    entries = []
    for name in ("gsdata_es.py", "es_clusters.py", "es_record_fields.py"):
        content = (source / name).read_bytes()
        (destination / name).write_bytes(content)
        entries.append(
            {
                "file": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "source": f"ACE/agent_framework/integrations/{name}",
            }
        )
    (destination / "SOURCE.json").write_text(
        json.dumps(
            {
                "source_head": "26993007caa7869bf10ddf0b29ec94f814145213",
                "files": entries,
                "policy": "只读协议快照；保持原始字节，不作为新业务实现修改。"
                "适配层位于 resources。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Pinned three credential-free ES protocol modules.")


if __name__ == "__main__":
    main()
