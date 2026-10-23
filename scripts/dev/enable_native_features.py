"""启用本机已安装的原生工作区能力，保留外部连接器配置。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: backend browser extra and Chromium; stopped Gateway; status-only stdout
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    path = ROOT / "deer-flow/config.yaml"
    config = yaml.safe_load(path.read_text("utf-8"))
    for key in (
        "agents_api",
        "scheduler",
        "mcp_tasks",
        "subagent_batches",
        "skill_evolution",
        "task_continuity",
        "tool_search",
    ):
        config.setdefault(key, {})["enabled"] = True
    config["scheduler"]["tool_enabled"] = True
    config.setdefault("projects", {})["summaries_enabled"] = True
    groups = config.setdefault("tool_groups", [])
    if not any(group["name"] == "conversation" for group in groups):
        groups.append({"name": "conversation"})
    tools = config.setdefault("tools", [])
    existing = {item["name"] for item in tools}
    for action in (
        "navigate",
        "snapshot",
        "click",
        "type",
        "get_text",
        "back",
        "screenshot",
        "close",
    ):
        name = f"browser_{action}"
        if name not in existing:
            tools.append(
                {
                    "name": name,
                    "group": "browser",
                    "use": f"deerflow.community.browser_automation.tools:{name}_tool",
                }
            )
    if "read_conversation" not in existing:
        tools.append(
            {
                "name": "read_conversation",
                "group": "conversation",
                "use": "deerflow.tools.conversation:read_conversation",
            }
        )
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(
        "Native agents, schedules, tasks, browser and conversation references enabled."
    )


if __name__ == "__main__":
    main()
