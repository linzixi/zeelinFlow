# 定时任务对话 403 修复

2026-10-23，账号 `1@qq.com`，所属团队管理员。

## 原因与修复

原生定时任务的 `fresh_thread_per_run` 在运行时直接创建对话，未保存项目归属。
ACE 部署策略要求对话属于当前团队可访问的项目，因此任务执行成功后，打开对话仍被拒绝。

- 定时任务增加持久化 `project_id`，0048 迁移只增加可空列，不推定历史归属。
- 页面新建任务必须选择当前团队的项目；既有任务的项目不可随普通编辑改变。
- 对话内创建任务继承来源项目；复用对话必须与任务项目一致。
- 调度启动前检查任务所有者、项目存续及部署权限，先建立项目对话，再进入正常运行准入；重试不重复建对话。
- 后台权限按任务固定项目及实时成员关系检查，不依赖用户当前浏览团队。审核员、撤权成员、外部账号不能执行。
- 列表、详情、运行历史按当前团队项目过滤，原生用户所有权检查保留。
- 已绑定项目的任务不依赖来源对话继续存在；未绑定的旧对话任务可从来源项目解析。

通用逻辑：`deer-flow/backend/app/gateway/scheduled_task_projects.py`。
团队规则：`extensions/ace/ace_ext/governance/scheduled_policy.py`。
项目选择器：`deer-flow/frontend/src/components/workspace/scheduled-tasks/project-select.tsx`。

## 已有数据修复

用户明确确认归属“上汽通用 · 舆情链”后，精确修复任务
`task-738aefb198c040e8b71f9fdbc5fb2bfa` 及其两次已完成运行的对话：

- `756a5ffd-85d3-4962-9034-c6444b265ae2`
- `06928c8c-d725-4c2e-9861-2815e3503ffe`

对应用户的原生项目为 `b3b4d7dadf0646128a84d0bfc70a4fa5`。
先停 Gateway 并备份数据库，再迁移及在事务内修复 NULL 归属；不覆盖已有非空归属。
脚本为 `scripts/verify/repair_scheduled_project.py`，默认仅检查，`--apply` 要求服务已停止。

任务启用状态、提示词、运行计数 2、原计划下一次时间（北京时间 2026-10-23 10:00:15）保持不变。
本次未触发任务、模型或通知，没有创建替代任务、画布或对话。

## 验证

- 后端定时路由、共享工具验证、群目标、一次性任务、仓储、项目归属和运行来源：380 项通过；唯一失败是旧列表测试未提供认证 state，补齐 fixture 后该项复验通过。
- 定时启动载荷 5 项通过；迁移及 bootstrap 6 项通过，3 项 PostgreSQL 测试因本地未配置 PostgreSQL 跳过。
- 真实本地 MySQL 权限回归 4 项通过，覆盖跨团队、他人、缺失项目、降为审核员和后台不依赖浏览团队。
- 前端表单 39 项通过，TypeScript、相关 ESLint 和生产构建通过。
- 以安装后的策略和真实持久化数据核对 `1@qq.com` 的任务、运行列表及两条对话读取权限，4 项均允许；没有伪造该用户会话。
- 在线 HTTP：管理员任务/项目返回 200，审核员任务/对话返回 403。
- 浏览器管理员会话检查项目选择器正常加载、选择；未提交创建。
- 原 ACE 仓库 status/diff/HEAD 未变化；上游 4228 文件无缺失，29 项原文件改动有清单，规模检查通过；未 commit/push。

证据位于 `output/verification/scheduled-project-{repair,owner-access,http}.json` 和
`output/verification/scheduled-project-form.png`；数据库备份路径记录在 repair JSON 中。
