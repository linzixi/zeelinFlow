"""只读迁移已授权本地模型配置到独立 DeerFlow 环境文件。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: legacy .env with LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
"""

from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import dotenv_values, set_key


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source = dotenv_values(root.parent / "ACE" / ".env")
    destination = root / "deer-flow" / ".env"
    values = {
        key: source.get(key) for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")
    }
    if not all(values.values()):
        raise SystemExit("原环境缺少模型配置；请配置独立模型后继续")
    for key, value in values.items():
        set_key(destination, key, value)
    config_path = root / "deer-flow" / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["models"] = [
        {
            "name": "ace-default",
            "display_name": "ACE 本地模型配置",
            "use": "langchain_openai:ChatOpenAI",
            "model": "$LLM_MODEL",
            "base_url": "$LLM_BASE_URL",
            "api_key": "$LLM_API_KEY",
            "max_tokens": 12000,
            "context_window": 128000,
        }
    ]
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print("Model configuration imported without displaying credentials.")


if __name__ == "__main__":
    main()
