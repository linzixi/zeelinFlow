# 上游存量文件拆分记录

本次不提交仓库、不创建远程 issue。以下是本地拆分 issue，满足旧项目硬规则的可审查记录；上游正式改动清单与净增行数由 `migration/upstream-changes.json` 逐文件保存。

| 本地 issue | 文件 | 本次最小改动 | 后续拆分边界 |
| --- | --- | --- | --- |
| DF-SPLIT-01 | backend/app/gateway/routers/threads.py | 列表部署策略过滤 | 按 CRUD、分支、状态/历史拆为路由子模块 |
| DF-SPLIT-02 | backend/app/gateway/auth_middleware.py | 调用通用授权钩子 | 身份解析、PAT、内部身份与响应映射拆为独立服务 |
| DF-SPLIT-03 | frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx | 新会话绑定项目 | 提交/再生成/人机交互逻辑拆为 hooks |
| DF-SPLIT-04 | frontend/src/app/workspace/agents/new/page.tsx | 创建 Agent 的对话绑定项目 | 名称校验和创建会话拆为 hooks |
| DF-SPLIT-05 | frontend/src/app/workspace/projects/[id]/page.tsx | 装配项目画布页、画布全宽、标签页手动激活避免双重离开确认 | 各项目标签页拆为 feature 组件 |
| DF-SPLIT-06 | backend/app/gateway/authz.py | 装配可选批量权限钩子，净增 5 行 | 权限解析、身份构建、装饰器拆为独立模块；批处理已置于 authorization_batch.py |
| DF-SPLIT-07 | backend/packages/harness/deerflow/integrations/lark_cli.py | SID 命令显式解码，净增 3 行 | Windows 凭据 ACL、CLI 子进程、OAuth、技能安装拆为独立模块 |

| DF-SPLIT-08 | backend/app/gateway/services.py | 调用独立 scheduled_task_projects 模块 | 运行准入、内部启动器与上下文解析分离 |
| DF-SPLIT-09 | backend/app/gateway/scheduled_task_access.py | 对话定时任务保存来源项目 | 工具权限、定义验证和结果投影分离 |
| DF-SPLIT-10 | backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py | create 接收 project_id | 定义 CRUD、调度租约与生命周期分离 |
| DF-SPLIT-11 | frontend/src/components/workspace/scheduled-tasks/task-form-dialog.tsx | 接入独立项目选择器 | 状态归一化、载荷构建和表单视图分离 |
| DF-SPLIT-12 | backend/tests/test_gateway_services.py、test_scheduled_task_router_behavior.py、test_run_origin.py | 补充项目归属相关 mock 契约 | 按准入、定时运行、来源元数据拆分测试 |
| DF-SPLIT-13 | frontend/tests/unit/components/workspace/scheduled-tasks/task-form-dialog.dom.test.tsx | 项目字段回归 | 载荷函数与交互 DOM 测试分离 |

原生新增实现均放独立文件；业务权限与项目映射在扩展内。基线脚本验证官方 4228 文件无缺失、仅允许逐文件清单中的变更，且继续验证旧 ACE 的 status/diff/HEAD 未变化。
