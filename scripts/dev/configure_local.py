"""初始化独立 DeerFlow 本地配置和扩展部署源，不覆盖已有配置。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: DeerFlow backend venv, built ACE browser assets
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    upstream = ROOT / "deer-flow"
    config_path = upstream / "config.yaml"
    if not config_path.exists():
        config = yaml.safe_load(
            (upstream / "config.example.yaml").read_text(encoding="utf-8")
        )
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
        config["database"]["sqlite_dir"] = str(ROOT / ".runtime" / "deerflow" / "data")
        config["run_events"]["backend"] = "db"
        # 原生每轮工具调用包含多个 middleware super-step，报告需要连续多次问数。
        config["recursion_limit"] = 400
        config["plugins"] = [
            {
                "name": "ace",
                "package": "deerflow-extension-ace",
                "use": "ace_ext:install",
                "enabled": True,
                "required": True,
                "config": {"env_file": str(ROOT / ".env")},
            }
        ]
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    extensions = upstream / "extensions_config.json"
    if not extensions.exists():
        extensions.write_text(
            '{"mcpServers": {}, "skills": {}, "middlewares": []}\n', encoding="utf-8"
        )
    destination = ROOT / ".runtime" / "extension-source"
    destination.mkdir(parents=True, exist_ok=True)
    source = ROOT / "extensions" / "ace"
    shutil.copy2(source / "pyproject.toml", destination / "pyproject.toml")
    shutil.copytree(
        source / "ace_ext",
        destination / "ace_ext",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print("Local configuration and extension source prepared.")


if __name__ == "__main__":
    main()
