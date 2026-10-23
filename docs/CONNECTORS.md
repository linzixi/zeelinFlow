# 配置与连接器契约

所有配置在 `ace_ext/core/config.py` 声明，对应根 `.env.example`。业务 MySQL 仅写 `ace_df_` 表；原生 DeerFlow 的账户、线程、checkpoint 与 run events 沿用其 SQLite，位于 `.runtime/deerflow/data`。

## 运行授权

`ACE_DF_AGENT_OWNER_ID` 与 `ACE_DF_AGENT_API_TOKEN` 必须属于同一原生用户。PAT 需 `threads:read`、`threads:write`、`runs:create`、`runs:read`、`runs:cancel` 范围。原生接口每次校验权限、所有权、失效和撤销。数据库中的用户 ID 不构成授权；重启使用部署凭据恢复观察原生 run，不调用内部 RunManager 绕过验证。

## 数据源

SGM专用HTTPS连接器为 `resources/sgm_source.py`。配置为 `SQTY_APP_ID`、`SQTY_APP_SECRET`、`SQTY_API_URL`；appId+timestamp签名，scheme_id[0..3]=51/52/43/55，50条分页。总数变化或分页不完整即失败。URL去重，完整raw保留，源入库时间采用push_time（北京时间）。2026-10-22 23:30–23:35窗口实际111篇、3页，无重复/空URL。SIS缺配置时按源项目策略使用已有正文，不伪造转写。

ES 节点在没有 `ACE_DF_SOURCE_URL` 时使用 `GSDATAS_ES_TOKEN` / `GSDATAS_ES_GATEWAY_URL`。保留 query_rounds、关键词及过滤字段、平台、聚类和精确计数复核。时间字段固定 `solr_create_time`，解析后再校验半开窗口 `[start,end)`。文档分页达到上限或异常短页会失败；簇候选集覆盖不等同全量召回，coverage 明确记录该限制。

设置 `ACE_DF_SOURCE_URL` 后，普通数据 Worker 向此受部署控制的基础地址发送 POST；令牌仅放 Authorization Bearer 请求头。桥接服务可对接爱品或现有数仓，不需要进入 Agent 沙箱。

| 路径 | 请求 | 成功响应 |
| --- | --- | --- |
| `/articles` | `window`、`node_type`、`config` | `{"complete":true,"records":[ArticleInput]}` |
| `/content` | `schemaVersion:1`、缺正文的 `records` | `{"contents":{"文章id":"正文"}}`，必须覆盖全部请求记录 |
| `/metrics` | `schemaVersion:1`、待刷新的 `records` | `{"metrics":{"文章id":{"reads":123}}}`，完整且为非负整数 |

`ArticleInput` 必含 `source_id`、`title`、带时区的 `ingested_at`；可含 url、source、content、published_at、branch（special/fund）、metrics 和 raw。输入只作为数据，不能改变工具授权。每条文章以来源 URL 或来源标识去重；首次入库时间固定，重复抓取不会成为新消息。`metrics` 使用平台文章id回写；同时携带的source_id/url/raw可供桥接查询业务系统。

## 执行和产物

输入/输出 `Envelope`：`schemaVersion:1`、records数组、summary字符串、context对象、artifacts数组。Agent 每次只收到一个节点的不可变输入。研判字段限定 sentiment/risk/decision/summary/tags；原文、版本及人工核验状态由平台维护。模型误引其他文章、遗漏批次或无效字段会停止下游。

报告返回 `artifacts:[{"name":"日报.md","content":"Markdown正文"}]`。平台将正文和可编辑 Word 保存在输出快照。下载由前端从已鉴权快照生成本地文件，不开放任意文件路径。

## 调度

各节点支持 manual/event/cron；独立定时报告从数仓截取配置时间窗，上游采集的完成事件只继续 event 节点。固定时点优先于 cron；修改无关画布字段不重置下一触发时间。启用开关、模拟/正式模式分别存入触发器。

MySQL 是领取和状态判断依据，Redis 仅发送可重复通知；缓存禁用或断线时保留 Outbox 并继续数据库扫描。Data/Agent/Delivery 各有并发通道。已知原生 run 在重启后继续观察；结果未知进入等待核对，确认原生终态后才允许显式新尝试。快照回溯固定历史输入与图版本，不能外发。
