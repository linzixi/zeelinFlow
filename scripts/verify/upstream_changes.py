"""记录经审核的 DeerFlow 集成改动，验证官方原文件哈希并计算净增行数。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: GitHub raw access; writes local manifest only
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SHA = "66508d7522015ab6582105130da691e2803eba0d"
REASONS = {
    "backend/app/gateway/routers/plugins.py": "公开已注册扩展工具的声明供能力中心展示，不授予执行权限",
    "frontend/src/core/extensions/api.ts": "解析扩展工具公开声明",
    "frontend/src/core/extensions/contracts.ts": "扩展工具目录类型",
    "frontend/src/components/workspace/capabilities/extension-gallery.tsx": "扩展详情显示工具及参数，搜索支持算子名称",
    "backend/tests/test_migration_0047_mcp_oauth_tokens.py": "迁移单链头前移至0048，保留0047升级降级测试",
    "backend/tests/test_run_origin.py": "定时启动来源测试补充已持久化任务契约",
    "backend/tests/test_scheduled_task_router_behavior.py": "复用对话测试补充项目元数据读取契约",
    "backend/tests/test_gateway_services.py": "定时启动载荷单测隔离新增项目准备步骤",
    "frontend/tests/unit/components/workspace/scheduled-tasks/task-form-dialog.dom.test.tsx": "项目选择必填与锁定归属回归",
    "frontend/src/core/scheduled-tasks/api.ts": "定时任务项目字段传输",
    "frontend/src/core/scheduled-tasks/types.ts": "定时任务项目字段类型",
    "frontend/src/components/workspace/scheduled-tasks/task-form-dialog.tsx": "定时任务表单选择所属项目",
    "backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py": "保存定时任务项目归属",
    "backend/packages/harness/deerflow/persistence/scheduled_tasks/model.py": "持久化定时任务项目归属",
    "backend/app/gateway/scheduled_task_access.py": "对话创建的定时任务继承项目",
    "backend/app/gateway/services.py": "定时运行前建立项目对话并检查部署权限",
    "backend/app/gateway/routers/scheduled_tasks.py": "定时任务显式项目归属与项目级列表过滤",
    "backend/pyproject.toml": "原生扩展管理器安装 ACE 包",
    "backend/uv.lock": "原生扩展管理器维护依赖锁",
    "backend/app/gateway/auth_middleware.py": "通用部署授权钩子",
    "backend/app/gateway/authz.py": "可选请求内批量权限钩子，避免重复读取团队成员关系",
    "backend/app/gateway/routers/personal_mcp.py": "普通用户内置能力安装兼容未提供的 cwd 扩展字段",
    "backend/packages/harness/deerflow/integrations/lark_cli.py": "Windows 中文用户名输出与 ASCII SID 解析隔离",
    "backend/app/gateway/routers/threads.py": "部署授权过滤线程列表",
    "backend/app/gateway/routers/projects.py": "部署授权过滤项目列表",
    "backend/app/gateway/routers/thread_activity.py": "部署授权过滤线程活动",
    "frontend/src/app/workspace/workspace-content.tsx": "团队访问边界装配",
    "frontend/src/components/workspace/workspace-sidebar.tsx": "团队切换与项目成员入口",
    "frontend/src/app/workspace/projects/[id]/page.tsx": "项目内画布标签页",
    "frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx": "Agent 对话绑定所选项目",
    "frontend/src/app/workspace/agents/new/page.tsx": "Agent 创建对话绑定所选项目",
    "backend/app/gateway/AGENTS.md": "记录部署授权接口维护契约",
    "frontend/AGENTS.md": "记录团队项目集成边界",
}


def inspect_file(path):
    cache = ROOT / "upstream-review/native-original" / path
    if cache.exists():
        content = cache.read_bytes()
    else:
        response = httpx.get(
            f"https://raw.githubusercontent.com/bytedance/deer-flow/{SHA}/{path}",
            timeout=40,
            follow_redirects=True,
        )
        response.raise_for_status()
        content = response.content
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(content)
    tree = json.loads((ROOT / "upstream-tree.json").read_text("utf-8"))["tree"]
    expected = next(row["sha"] for row in tree if row["path"] == path)
    assert (
        hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        == expected
    ), path
    modified = (ROOT / "deer-flow" / path).read_bytes()
    before, after = len(content.splitlines()), len(modified.splitlines())
    if path.endswith((".py", ".tsx")):
        assert after - before <= 50, (path, after - before)
    return path, {
        "reason": REASONS[path],
        "original_blob": expected,
        "original_lines": before,
        "current_lines": after,
        "net_added": after - before,
        "sha256": hashlib.sha256(modified).hexdigest(),
    }


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifest = dict(pool.map(inspect_file, REASONS))
    (ROOT / "migration/upstream-changes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Verified {len(manifest)} explicitly reviewed upstream integration files.")


if __name__ == "__main__":
    main()
