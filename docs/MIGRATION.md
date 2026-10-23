# 迁移映射与保留方式

源项目：CMC `proj_b33b4901cd79` revision189，15节点/17连线。只读导出保存于 `migration/source/cmc-realtime.json`。由于源指令曾漂移至全天120分钟，当前导入按用户明确要求恢复六个北京时间固定时点和150分钟入库窗口；旧正式项目未改。

| 原节点 | 新执行职责 |
| --- | --- |
| clock / time | 固定时点触发、冻结时间窗；普通数据任务 |
| special_search_1/2/3 / fund_search | ES查询或数据桥接 → MySQL文章库 |
| fund_clean | 标准化与去重；普通数据任务 |
| common_content | 读取已有正文，仅缺失部分调用正文连接器 |
| common_prepare | 数据整理、保留分支及输入上下文 |
| special_processing / fund_processing | 分支独立的 DeerFlow Agent 风险判断 |
| special_document / fund_document | DeerFlow报告节点 → Markdown与Word快照 |
| special_push / fund_push | 按实时/历史/时段策略保存未发送预览 |

节点库还提供互动刷新、历史比对、结果入库、事件去重和分类节点。保留旧type_id，图仍可用原节点名查找。历史比对以本轮开始前的已入库分析为基线，不宣称已有外部发送记录。客户原来存放在旧沙箱的脚本文件尚未搬运，迁移图保留业务要求；需要实际脚本时应作为DeerFlow技能/工具安装并绑定，不复用旧沙箱绝对路径。

## Schema

1. `durable_canvas`：projects、graph_revisions、articles、article_revisions、snapshots、runs、tasks、task_attempts、events、outbox、schedules；显式InnoDB和DOUBLE时间戳。
2. `transactional_migrations`：迁移元数据表也使用InnoDB。
3. `archive_legacy_validation_payload`：将只为溯源复制的source_config从编辑图移除，旧图修订仍保留完整副本；增加图revision，避免超出原生256KiB请求限制。
4. `teams_workspaces`：团队、成员角色、团队项目、画布归属与用户原生项目映射。
5. `agent_batches`：可恢复模型批次、原生thread/run及持久结果。

统一迁移入口 `scripts/migrations/20261022_ace_schema.py`；重复执行不丢已有版本。MySQL使用READ COMMITTED，防止并行父节点各自读旧快照后错过下游汇合。

## 原生能力与边界

DeerFlow源码保留原生对话、Agent配置、技能、MCP、记忆、子Agent、文件/沙箱和认证；本扩展通过官方BrowserAssets与BackendAction进入现有工作区和Gateway。当前生产HTTP入口仍是原生Gateway，没有在旧ACE、冻结server或兼容出口增加功能。

新本地目录没有提交/推送。官方导入文件的依赖、通用授权钩子与页面集成变更由 `migration/upstream-changes.json` 显式登记和校验；vendor中的三个ES协议文件保持原ACE字节，并附SOURCE.json来源与SHA256。新增模块/函数/组件按600/80/300行限制拆分。

SGM只读导出为 `migration/source/sgm.json`，源项目 `proj_e67b65830e37` revision209。16个节点ID/type保留。完整分页接口签名、4个方案、过滤、情感/问题提示词、11类问题编码、24小时关联、媒体与新浪规则迁入独立模块；飞书节点只生成卡片预览。原SIS配置允许fallback-to-source，本机未配置SIS，保留证据限制。

本机既有 `1@qq.com` 账号已加入两个示例团队，原对话归属保持本人并绑定SGM个人项目容器，没有重置密码。迁移前线程元数据与修订记录在 `.runtime/legacy-thread-before-project.json` 和MySQL事件表中。

回退扩展时先停本工程Gateway，再通过原生扩展管理器禁用/卸载ACE并重启；保留MySQL ace_df_表、根.env和.runtime目录以便恢复。不得直接删除旧业务表、旧ACE项目或按名称清理项目。
