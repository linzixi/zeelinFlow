# 上汽通用原画布迁移对照

原项目 `proj_e67b65830e37`，revision 209；只读导出保存在 `migration/source/sgm.json`。迁移修改既有画布 `a12c17265319471eb3dc6bd659265c81`，保留 16 个节点 ID、原 16 条边、条件与业务配置，在末尾增加智能问数报告节点和两条依赖边。编辑使用 revision CAS，运行冻结对应图版本。

## 逐节点落点

| 原节点 | 新执行位置 | 保留行为与验收方式 |
| --- | --- | --- |
| 1. 5 分钟窗口 | 数据队列 / window | 北京时间入库半开区间；手动验收指定历史完整窗口，cron 可编辑 |
| 2. SGM 定制取数 | resources/sgm_source.py | 原方案集合、签名、分页；保存 total/fetched/unique/complete，不默默截断 |
| 3. 标准化入库 | execution/sgm_data.py normalize | 原始字段保留、URL 去重、中文标题指纹；无标题占位不作为中文证据 |
| 4. MySQL 准入 | execution/sgm_data.py prepare | 三种发送/占用状态、原创、回复、首标签、中文证据等原规则 |
| 5. type=2 情感 | execution/sgm_agent.py | 原 prompt 业务口径；原生 DeerFlow 真模型，分批持久回执；人工标签优先并影响分支 |
| 6. SIS / ASR | sgm/transcription.py | 技术平台 video/media_toutiao 且存在 videoURL；先下载后转写；轮询释放 Worker；保存外部 job、来源 hash、转写 hash |
| 7. type=3 提取 | execution/sgm_agent.py | 仅有效负面进入；提取车型、原文、问题与分类；不得用 type=3 的意见否决 type=2 负面 |
| 8. 分类映射 | sgm/business.py mapping | 原车型、问题、媒体属性映射与首/二/三级标签；保留人工字段 |
| 9. 24 小时同题 | execution/sgm_data.py related | 同项目、同模式、24 小时、同指纹、不同 URL；过滤已删除及发送状态关闭记录 |
| 10. 决策门禁 | sgm/delivery.py | 原发送状态与新浪过滤、头条真实 ETL 校验；摘录不匹配时清空摘录转人工，负面不丢失 |
| 11. 租约/重试 | persistence/tasks.py + outbox | MySQL 权威状态、lease fencing、输入快照、恢复和幂等；不重复启动回执不明的外部任务 |
| 12. Schema 2.0 卡片 | vendor/legacy_sgm/card.py | 原卡片结构与关联链接；仅对实际装进卡片的链接做本轮去重，不修改真实发送占用 |
| 13. 发送前质检 | execution/sgm_data.py quality | Schema 2.0、元素完整、30KB 上限、禁止 delivered 标记 |
| 14. 发送/事务回写 | execution/sgm_data.py receipt | **按用户要求仅本地预览**；记录 would_send、原延时、effect_key，external_messages_sent=0 |
| 15. 媒体识别 | execution/sgm_data.py route | 每篇独立 text/video/complete；跳过文章不进入模型 |
| 16. 条件分支 | persistence/task_state.py | 按文章路由分派，文字不误入 SIS，视频不提前进入情感；汇合去重后进入模型 |

`vendor/legacy_sgm/SOURCE.json` 记录原文件哈希。没有复制飞书发送函数。模型凭据从本机配置取值，不进入节点配置、图导出、报告或日志。

## 明确的执行差异

- 模型运行迁入 DeerFlow 原生 Agent，使用当前有效模型；原业务 prompt 与枚举保留，随机模型结果不能承诺与旧供应商逐字一致。
- 数据任务在 MySQL/Redis 队列运行，Agent 只读取该节点输入。SIS 等待期落库并释放执行槽。当前合流以批次节点完成为边界，尚不是逐篇文章贯穿全图的流式执行。
- SIS 成功结果可按来源 hash 复用；失败保留原因。原 worker 的 `fallback-to-source` 允许在终态后基于现有标题/正文分析，不能将此称作成功转写。`skip` / `fail` 配置也生效。
- 原画布说明“禁止仅凭视频标题”与旧 `pipeline.py::_finish_sis_downstream` 的终态降级逻辑不同；执行依据后者，并向模型、文章及报告显式传递降级状态。
- 原普通/图片延时在预览回执保留；此次没有真实等待后发消息，也没有将预览当成真实发送成功。业务 cron 默认关闭，用户可在画布配置后启用。
- 新增问数节点等待情感与预览回执完成，冻结数仓文章版本；不会把报告内容写回预警文章。

## 验收证据

最终通过结果由 `scripts/verify/sgm_parity_acceptance.py` 生成在 `output/verification/sgm-parity-acceptance.json`，含每节点状态及输入/输出快照、完整分页、转写/降级数量、人工覆盖、模型工具调用和零外发断言。失败与取消的尝试仍留在运行历史，不能当作通过证据。

本轮修复了无标题占位导致错误准入、模型抄错长 ID、降级上下文缺失、人工标签与路由不一致、报告基准统计混用过滤条件等问题；相关真实数据库回归见 `extensions/ace/tests`。
