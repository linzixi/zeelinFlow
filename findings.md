# 调研记录

## 第三阶段最终发现

- 原SGM画布说明与旧worker的终态降级逻辑存在差异；按pipeline.py的fallback-to-source运行，必须显式携带media_route/sis_status/content_status/evidence_limit，不能把源标题分析称为视频转写。
- 空白标题的UI占位不能成为中文准入证据；模型使用短ID映射避免长ID抄错。有效情感落库后重新计算路由，人工负面不会被模型中性分支漏掉。
- SIS真实63任务中37成功、26降级。跳过文章可能保留旧轮次转写状态，报告按assessment_status过滤后才是本轮口径，不能直接按历史sis_status汇总。
- 报告必须强制无过滤全量总览/平台/来源/问题/时间线基准，避免分母混用；典型文章可筛选。无法匹配原文的摘录不能伪装成引文。
- DeerFlow每次模型/工具循环含多个中间件步骤，原recursion_limit=100不足以完成多轮问数；设400后8次实际查询成功。报告解读限长，避免模型网关长输出502。
- 审核表单只提交差异字段，否则只改状态也会把所有自动字段标为人工覆盖。浏览器和真实数据库回归均通过。
- 热更新附近一次list_runs 500响应为空且服务日志无堆栈；稳定刷新后列表和详情持续200，当前仅能记录未复现，不能断言已找到根因。

## 2026-10-22：需求与基线

- 旧仓库 E:/work/QB项目/ACE/ACE，HEAD 26993007caa7869bf10ddf0b29ec94f814145213。已有 AGENTS.md 修改及许多未跟踪内容，均保留。
- 已读 docs/CODE_CHANGE_GUIDELINES.md 与 docs/canvas-validation-lifecycle.md。
- 图 1：画布负责控制与观测；数据资产独立持久化；Scheduler→Queue→普通 Worker/Model/Agent Sandbox；Outbox 触发下游，按数据快照追溯。
- 图 2：多源异步采集→原始数据入库→标准化→规则/标签/情感判断→结构化结果；预警、互动刷新、报告为独立任务；支持人工干预与多产物。
- CMC realtime 项目 proj_b33b4901cd79：08:30/10:30/12:30/14:30/16:30/18:30，回看入库时间 150 分钟并去重，定时发送 09:00 ≤ 北京时间 < 20:00，首轮完成早需等待 09:00；历史数据不能外发。

## 上游

- GitHub API 确认 2026-10-22 main：66508d7522015ab6582105130da691e2803eba0d，2.2.0-dev。Git HTTPS 被重置，采用官方 codeload 固定 SHA 下载，不使用第三方镜像。
- 新版原生 Gateway 已内嵌 LangGraph，extension-api 提供 PluginContribution / BrowserAssets / AgentRuns，扩展优先，能够保留原生前端/能力。
- AgentRuns 服务持有句柄仅本进程有效，重启需要新授权。定时沙箱持久治理不能绕过这一边界，需要后续针对宿主调度授权实现。

## 现有画布实测

- 已按旧 .env 中的 tenant 只读查询原数据库，CMC revision 189，15 节点；脱敏导出 migration/source/cmc-realtime.json。
- 原项目当前 instructions 已变为全天120分钟/当日累积窗口，与用户本轮 AGENTS 的固定时点和150分钟要求冲突。迁移样例必须按用户要求修正，旧项目不改。
- 本地 drama2seed 已有其他业务表，因此只新增 ace_df_ 表，不复用或改动旧 project/article/workflow 表。

## 已验证

- 图校验/乐观并发/跨用户隔离、文章修订保护/不可变快照、队列扇出/重试/租约 fencing/取消/回溯合计11项离线测试通过。

## 持久运行适配

- 使用部署方原生PAT，通过公开threads/runs接口逐次鉴权；不序列化AgentRuns权限句柄。线程和请求幂等键以task/attempt派生，重启继续观察已知运行。
- MySQL默认MyISAM导致事务语义不成立，迁移显式InnoDB；并行父节点快照测试复现REPEATABLE READ遗漏汇合，连接统一READ COMMITTED后通过。
- 真实模型第一次401，用户更新根.env而非deer-flow/.env，启动参数已改读根文件。

## 最终验证发现

- DeerFlow插件action请求体上限256KiB；旧validationSuite副本导致编辑图699758字节，移入历史后保存成功。不能扩大宿主限制掩盖重复载荷。
- 原生模型曾将artifacts输出成对象；契约拒绝结果，补充精确JSON数组结构后真实研判/报告验证成功。
- 模型结果必须通过id范围、枚举及完整批次校验；人工review_status不接受模型赋值。持久结果更新后将新revision回传下游，过时结果保留诊断并使用当前人工版本。
- 全屏和点击节点聚焦提升大图可读性；分组拖动实测同时移动成员，并保存包含实际成员的边界。

## 第二阶段设计
- 团队项目共享画布/文章，原生项目按用户投影，保留 DeerFlow 个人对话所有权约束。
- 一个账号可在不同团队担任不同角色；审核员不挂载原生操作界面，后端拒绝原生 API。
- 上汽通用实际源项目 proj_e67b65830e37 revision209，共16节点；接口签名必须 appId+timestamp，并发送 app_id 别名和 PHP 下标数组。
- 现存源码只读；分页覆盖不完整必须停止，飞书只预览。

## 项目治理与SGM发现

- 原生项目/对话是个人资源，团队共享画布用MySQL工作区映射保留原生所有权。审核员必须在后端拦截原生API，单纯藏菜单不够。
- LangGraph SDK会重复创建已预建的附件会话；必须允许本人当前团队已有线程的幂等创建，不能放开无项目新建。
- SGM签名使用appId并传PHP索引scheme_id；一级标签读取news_first_tag，入库时间读取push_time；111篇3页覆盖已核对。
- 视频源项目明确fallback-to-source；SIS未配置时标记证据限制。模型情感与提取可能矛盾，预览前逐段验证摘录，证据不足进入人工核验。
- 原生浏览器下载单连接反复超时；改用官方HTTPS分段下载并校验Content-Range和ZIP CRC，原生Chromium实际启动成功。
