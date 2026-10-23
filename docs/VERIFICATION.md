# 本地迁移验收记录

## 第三阶段最终验收：原流程、页面与智能问数（2026-10-23）

入口：`http://127.0.0.1:3000/workspace/projects` → 汽车客户团队 → 上汽通用 · 舆情监测 → 画布与预警。当前画布版本v8，真实主运行冻结v7；v8仅补充报告的自然语言处理要求。旧ACE及参考目录只读，未提交或推送。

| 验收项目 | 最终结果 |
| --- | --- |
| 页面修复 | 项目画布使用完整宽度；1440/768/390宽度及底部工具栏可用；未保存离开只弹一次确认；文章只提交修改字段，避免状态编辑锁住其它模型字段 |
| ACE样式 | 深色点阵、分类色、选中与运行状态、连线动效和分组边界；已核对17节点全成功截图 |
| 项目与权限 | 项目内建立画布，新对话必须指定项目；多团队三角色可切换；审核员仅见5篇候选，普通文章、画布、运行和原生操作接口拒绝 |
| 原图对照 | revision209的原16节点/16边保留；新增报告1节点/2边。逐节点规则与执行差异见[SGM-PARITY](SGM-PARITY.md) |
| 数据完整性 | 北京时间2026-10-22 23:30–23:35，真实接口3页111篇；无重复/空URL，覆盖完整 |
| 准入及打标 | 106篇分析，5篇跳过（无中文3、微博转发1、回复1）；负面5、中性76、正面25、未知5 |
| SIS视频 | 63个真实任务：37转写成功、26降级；降级中21无转写、5下载失败；无需转写43，跳过5不计转写成功或降级 |
| 提取与预览 | 5篇有效负面全部进入type=3；4篇摘录匹配、1篇摘录清空待人工；原卡片结构生成5张本地预览，真实外发0 |
| 人工修改 | XTS文章的问题“尾门无法关闭（依据现有文字）”和watching保留；浏览器只追加修订说明后v57、历史记录可回查；主运行无过时分析事件 |
| 智能问数 | 实际读取CSDN案例；模型真实调用MySQL只读算子8次，111篇冻结数据集；查询口径/结果/文章版本和引用可审计 |
| 报告产物 | 独立HTML、可编辑Word、Markdown、4张SVG与审计JSON；工作台HTML/SVG预览成功；Word页面下载后与导出文件逐字节一致，79段正文/5张表解析通过 |
| 自动检查 | 本轮59项真实MySQL后端测试、5项扩展UI测试；原生tsc、受影响页面ESLint、扩展TypeScript/Vite构建和Ruff通过 |
| 最终代码基线 | 旧ACE的status/diff哈希与HEAD不变；官方4228文件无缺失，13处显式集成修改均有哈希与净增行数登记；新代码规模无违规；[基线JSON](../output/verification/baseline.json) |

**执行记录**：主流程 `86b4548bdc2a406ea16e1e900232a9b8` 为17/17完成。其首次报告核对发现一篇跳过文章残留旧轮次转写状态，导致降级统计为27；修复统计后仅回溯报告节点，运行 `eb7fd8d9e8c54888b1f72e5e478979bf` 为1/1完成。下列最终报告来自这个回溯运行，降级数为26。没有重新取数或修改主运行历史，失败/取消尝试仍保留。

最终证据：[逐节点验收JSON](../output/verification/sgm-parity-acceptance.json)、[主运行](../output/verification/sgm-parity-live.json)、[最终报告运行](../output/verification/sgm-report-final.json)。产物：[HTML](../output/sgm-report/上汽通用舆情报告.html)、[Word](../output/sgm-report/上汽通用舆情报告.docx)、[查询审计](../output/sgm-report/数仓查询审计.json)。问数配置与四算子见[使用说明](INTELLIGENT-REPORTS.md)。

浏览器证据位于 `output/playwright/`：`stage3-canvas-success-final.png`、`stage3-canvas-768-final.png`、`stage3-canvas-390-final.png`、`stage3-teams.png`、`stage3-reviewer-saved-final.png`、`stage3-reviewer-history-final.yml`、`stage3-report-preview-final.png`、`stage3-one-confirm.yml`、`stage3-new-chat-project.yml`。窄屏截图用于布局验收，其较早运行状态不作为成功证据。最终浏览器复核摘要见[浏览器证据](../output/verification/stage3-browser-final.json)。

**观察项**：前端开发热更新附近曾有一次`list_runs`空响应500，服务日志没有足够堆栈确定根因。稳定刷新并再次切换运行/画布后，列表和详情请求持续200，未复现；网络记录见 `output/verification/stage3-browser-requests.txt`。保留该观察，不声称历史控制台完全无错误。

**范围与边界**：原业务节点/规则迁移，模型换为当前DeerFlow配置，不能承诺与旧模型逐字一致。数据/Agent任务独立，SIS等待释放Worker，但合流仍按批次完成，尚非逐篇端到端流式运行。业务cron默认关闭；真实飞书按要求替为预览。远程云沙箱未部署；原生个人资源仍按账号持有，并非完整企业多租户产品。五分钟样本不能支撑七日增长、全网或影响力推断；报告已明确区分入库节奏、源正文、转写失真与待核实候选。

## 第二阶段历史验收：项目、团队权限与SGM真实数据（2026-10-23）

以下数字与SIS配置状态是第二阶段当时结果，当前以第三阶段最终验收为准。

入口：`http://127.0.0.1:3000/workspace/projects`。选择汽车客户团队 → 上汽通用 · 舆情监测 → 画布与预警。已有 `1@qq.com` 账号可用，密码未改；示例成员及本机密码文件见README。

| 验收项目 | 实际结果 |
| --- | --- |
| 项目与画布 | 项目内建立/选择画布，保留原生对话、资料、说明和设置；一个项目支持多个画布 |
| 对话归属 | 普通/自定义Agent/Agent创建会话必须选项目；附件先绑定项目，SDK幂等创建不会丢失归属；真实Agent读回上传文件标识 |
| 多团队角色 | 管理员、编排师、审核员可操作；同一示例编排账号切换团队后变审核员；既有账号加入两团队 |
| 审核权限 | 审核员页面只显示5篇预警候选；原生聊天、模型、Agent、画布、运行API拒绝；普通文章历史和编辑拒绝；跨团队线程拒绝 |
| 人工修订 | 浏览器改动XTS文章的问题概述与观察状态，刷新保留；修订历史记录审核账号和说明；过期revision提交被拒绝 |
| 功能开启 | Agent API、定时任务及工具、MCP后台任务、持久子任务批次、技能演进、任务连续性、工具搜索、项目摘要、对话引用、浏览器控制已开启；官方Chromium安装并实际启动通过 |
| 实际数据 | 2026-10-22北京时间23:30–23:35；SGM定制接口3页111篇，完整覆盖、无空URL/重复 |
| 情感与问题 | 28正面、76中性、5负面；2篇按规则跳过，109篇完成分析；负面文章完成车型/问题提取或明确记录证据不足 |
| 证据与预览 | 5篇进入人工核验，其中4篇摘录与原文匹配，生成4张卡片；1篇情感/提取分歧，只留人工核验。实际发送0条 |
| 执行记录 | 首轮16/16节点；媒体分流后的数据再处理11/11节点；证据规则重检5/5节点。仅同一画布，不重建副本，不重复取数/情感 |
| 工程检查 | MySQL下46项扩展测试、2项原生授权钩子测试、2项前端图逻辑测试通过；原生tsc、修改页面ESLint、扩展构建、Python Ruff通过 |
| 代码基线 | 旧ACE status/diff/HEAD不变；官方4228文件无缺失；13处显式上游集成改动有哈希和净增行数记录，新增代码规模检查通过；未提交/推送 |

证据：[SGM汇总](../output/verification/sgm-acceptance.json)、[当前预览卡片](../output/verification/sgm-feishu-preview.json)、[权限回归](../output/verification/team-access.json)、[审核与真实附件会话](../output/verification/final-checks.json)、[基线](../output/verification/baseline.json)。截图见 `output/playwright/reviewer-real-articles.png`、`reviewer-saved-edit.png`、`project-chat-attachment.png`、`team-management.png`。

运行ID：主流程 `0d0146985862479d8b6014b0d5b73011`，媒体后续 `585bfed9fcaa4f1c91d00eff652eb811`，证据重检 `3716e0cd41094741a4951b9e754ec32c`。模型网关曾超时/502，重试后成功；批次状态、失败尝试和输入输出保留，没有将失败结果冒充成功。

**边界**：3篇负面视频按原画布 `fallback-to-source` 使用现有标题正文，未实际调用SIS转写，文章界面标明此限制。外部RAG、SIS、远程云沙箱、图片/语音服务和消息渠道尚需真实配置。团队共享画布/文章，原生对话/资料、记忆/个人Agent仍按账号持有；这不是完整企业多租户隔离。无人值守PAT仅为主账号配置。示例业务cron关闭，飞书与其他消息渠道均未启用。

## 第一阶段历史验收（以下为当时范围）

日期：2026-10-22。范围：官方DeerFlow工作区内的ACE扩展、CMC画布模拟、本地MySQL/Redis、真实模型与本地文件沙箱。

## 已通过

| 验证 | 结果与证据 |
| --- | --- |
| 后端 | 实际本地MySQL下37项测试通过，覆盖迁移、CAS、作用域隔离、并行汇合、租约恢复、重试、定时、人工修改保护与原生运行恢复 |
| 前端 | TypeScript/Vite构建与2项图逻辑测试通过；Ruff静态检查与格式检查通过 |
| CMC流程 | 15/15节点成功；6篇合成文章、2篇高风险；仅保存发送预览 |
| 浏览器编辑 | 节点名称、连线、分组拖动和实际边界可保存并刷新恢复；文章人工确认在重跑后保留；单节点快照回溯、全屏、节点聚焦和390px窄屏检查通过 |
| 真实Agent工具 | 原生ls/write_file/read_file执行并校验文件标记；见[运行证据](../output/verification/live-node.json) |
| 真实研判与报告 | 两篇合成资料经真实模型研判→报告生成Markdown和Word；见[运行证据](../output/verification/live-pipeline.json) |
| Word下载 | 浏览器下载成功，python-docx解析正文通过；见[样例报告](../output/verification/cmc-simulation.docx) |
| 进程重启 | 最终脚本重启后数据库/Redis正常、8个Worker、schema v3；1个可见项目、画布v5、6篇文章及成功运行记录均保留；见[重启证据](../output/verification/restart-health.json) |
| 旧仓库与上游 | 旧status/diff哈希和HEAD不变；官方4228文件无缺失，仅扩展管理器维护依赖声明和锁文件；见[基线证据](../output/verification/baseline.json) |
| 本机账号脚本 | 已有账号重复登录成功；通过auth/me读取身份；不重置密码、不输出密钥 |

界面截图位于[output/playwright](../output/playwright/)。稳定页面加载后的浏览器控制台为0错误、0警告；部署切换期间的历史日志不属于稳定运行检查。

## 未包含的生产验收

- 正式ES/爱品新闻数据源尚未配置有效凭据或桥接地址，当前未验证真实取数。
- 真实Agent使用DeerFlow本地文件沙箱，禁止宿主机bash；远程云沙箱、原客户脚本执行尚未配置。
- 外部推送仅保留预览，本次没有发送钉钉或其他消息。
- 单次Agent输入上限200KB，尚未自动分片；Word为基础可编辑正文，尚未迁移客户专属版式；月报预设为滚动31天。

这些边界不应被理解为已完成生产部署。后续接入与授权配置见[CONNECTORS.md](CONNECTORS.md)，使用方式见[README](../README.md)。
