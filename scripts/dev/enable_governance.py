"""启用本机团队权限提供者，保留其余模型和服务配置。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: installed ACE extension; stopped Gateway; stdout contains status only
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    path = ROOT / "deer-flow/config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["authorization"] = {
        "enabled": True,
        "fail_closed": True,
        "default_role": "user",
        "provider": {
            "use": "ace_ext.governance.policy:TeamAuthorization",
            "config": {"env_file": str(ROOT / ".env")},
        },
    }
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print("Team authorization configured.")


if __name__ == "__main__":
    main()
