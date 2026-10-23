# ACE on DeerFlow

在官方 DeerFlow 上增加可编辑画布、预警文章库和持久节点调度。旧 ACE 仓库不参与运行，也没有被修改。此目录未提交或推送 Git。

官方基线：2026-10-22 `main`，`66508d7522015ab6582105130da691e2803eba0d`（2.2.0-dev）。4228 个源文件已按 Git blob 校验。业务逻辑位于 `extensions/ace`；原生工作区增加项目/团队入口，网关增加可选部署授权钩子。逐文件变更、净增行数与拆分记录见 `migration/upstream-changes.json` 和 `docs/UPSTREAM-SPLIT-ISSUES.md`。

## 本机使用

查询算子可在 **能力中心 → 扩展插件 → ACE 工作台 → 扩展算子** 查看。详情展示已注册工具的用途、启用状态及参数定义；扩展插件页支持按算子名称搜索。`project_review_queue` 用于项目实时审核数量与文章明细，`warehouse_query` 用于报告节点的冻结数仓快照。入口：`/workspace/capabilities?tab=extensions&extension=qingbo.ace`。

在本目录运行：

```powershell
./scripts/dev/start-local.ps1
```

日常启动使用已预构建的正式前端，避免点击页面时现场编译。首次安装或修改原生前端后，先运行 `./scripts/dev/build-local.ps1`；重建前只需 `./scripts/dev/stop-local.ps1 -Service frontend`。仅源码调试使用 `start-local.ps1 -Development`。卡顿排查证据见 [PAGE-PERFORMANCE](docs/PAGE-PERFORMANCE.md)。

打开 **http://127.0.0.1:3000/workspace/projects**。选择团队，再进入项目的“画布与预警”页；一个项目可建立多个画布。新建普通对话、自定义 Agent 对话及 Agent 创建会话均必须选择项目。项目原有对话、资料、说明和设置页保留。后端为 `127.0.0.1:8001`。

主账号 `ace@example.com` 的密码在 `.runtime/local-login.json`；示例账号密码在 `.runtime/team-demo-accounts.json`，没有发送邀请。`ace.manager@example.com` 是汽车客户团队管理员；`ace.editor@example.com` 在汽车客户团队是编排师，在清博智能团队是审核员；`ace.reviewer@example.com` 是汽车客户团队审核员。

| 当前团队角色 | 项目、画布与运行 | 对话、Agent、能力中心 | 预警审核编辑 | 成员管理 |
| --- | --- | --- | --- | --- |
| 团队管理员 | 允许 | 允许，仍遵守原生账户权限 | 允许 | 允许 |
| 编排师 | 允许 | 允许，仍遵守原生账户权限 | 允许 | 禁止 |
| 预警审核员 | 禁止 | 禁止 | 仅预警文章 | 禁止 |

审核员进入专用文章界面，后端同步限制接口。团队共享画布和文章；原生对话与资料继续由账号个人持有，打开团队项目时建立个人项目映射。原生记忆、个人 Agent 和技能仍为账号级资源，此示意不是完整企业多租户改造。

根 `.env` 是模型和 ACE 数据库配置的统一入口。你提供的本地 MySQL / Redis 和更新后的模型凭据已保留在该文件；启动脚本不再读取旧的 `deer-flow/.env` 模型值。日志位于 `.runtime/*.log`。

`stop-local.ps1` 只停止由 `start-local.ps1` 创建且命令行归属匹配的进程。终端前台调试使用 `run-local.ps1 -Service gateway` 或 `-Service frontend`，按 Ctrl+C 停止。强制停止后由 MySQL 租约恢复未完成任务。

## 验收路径

1. **可视化编排**：在项目内选择上汽通用或 CMC 画布，点全屏；点击节点可聚焦并编辑名称、执行方式、提示词、Skill、配置、触发器。拖动节点；按住 Shift 多选建组；拖动分组标题移动成员。连线可修改条件和名称。保存使用 revision 校验。
2. **运行方式**：CMC 模拟使用六篇明确标记的合成文章。SGM 正式模式已接入真实数据和 SIS，保留原16节点，新增一个智能问数报告节点。手动运行前核对模式与时间窗；推送节点只保存预览。
3. **预警文章**：支持修改标题、摘要、情感、风险、标签、核验状态；SGM额外支持车型、问题概述和负面原文。每次修改保留历史，自动分析不能覆盖人工修订。审核员只见 decision 为 report/review 的预警文章。
4. **运行记录**：查看节点耗时、尝试次数、输入输出快照和校验值；按原快照回溯单个节点，或重试已失败任务。Agent 任务可打开原生 DeerFlow 会话。报告输出可预览 HTML/SVG、下载 Markdown 和可编辑 Word。
5. **智能问数与周期报告**：在“上汽通用 · 智能问数报告”的处理要求中写自然语言问题，指定报告区间。Agent 实际调用 MySQL 只读总览、分组、时间线与文章查询，生成带可回查证据的报告。也可配置独立定时触发；采集分支不会顺带触发独立定时节点。月报预设是滚动31天，尚非自然月统计口径。详见 [智能问数说明](docs/INTELLIGENT-REPORTS.md)。

每个节点可设置独立周期、回看窗口和启停；操作步骤、Cron示例、事件衔接与现有限制见 [节点定时说明](docs/NODE-SCHEDULING.md)。节点时钟不在侧栏的原生“定时任务”页管理。

CMC 首次导入源项目 `proj_b33b4901cd79`，revision189；SGM源项目 `proj_e67b65830e37`，revision209，保留16个节点ID/type。各有一个示例画布，测试数据使用隔离租户。原正式项目没有改动，示例定时触发默认关闭。

## 已验证

- 本地 MySQL 的版本迁移、并行父节点汇合、CAS、所有权隔离、快照、人工覆盖保护、租约恢复、Redis 故障兜底、定时和原生运行恢复测试。
- 原生工作区浏览器：CMC 15/15 节点成功、6篇文章、2篇高风险，文章人工确认保留，节点及连线修改保存后刷新保留。
- 真实模型：原生 `write_file` / `read_file` 工具成功；两篇合成新闻完成真实研判 → 报告，并生成 Markdown / Word。
- SGM最终真实验收：2026-10-22 北京时间23:30–23:35完整取数111篇，106篇完成分析、5篇按原规则跳过；负面5、中性76、正面25。63篇视频中37篇成功转写、26篇终态降级。5篇负面进入原type=3提取，4篇摘录核验通过、1篇清空摘录待人工；5张本地预览卡片，实际发送0条。
- 主流程17/17节点完成；报告统计核对后仅回溯报告节点1/1完成，最终报告含8次真实数仓工具调用。可直接查看 [HTML报告](output/sgm-report/上汽通用舆情报告.html) 或 [Word报告](output/sgm-report/上汽通用舆情报告.docx)。完整逐节点对照见 [SGM-PARITY](docs/SGM-PARITY.md)。
- 本轮59项真实MySQL后端测试、5项扩展UI测试通过；原生类型检查、受影响页面ESLint、扩展TypeScript/Vite构建和Ruff检查通过。浏览器覆盖项目/会话归属、团队权限、审核编辑、单次离开确认、1440/768/390宽度及报告下载。
- 证据位于 `output/verification/`，界面截图位于 `output/playwright/`。这些是本地产物，不进入版本库。
- 完整验收记录见 [docs/VERIFICATION.md](docs/VERIFICATION.md)，含重启恢复与未包含的生产接入项。

## 当前范围

这是以 CMC 和 SGM 真实画布为样例的可运行迁移版本。已开启 Agent API、原生定时任务及工具、MCP后台任务、持久子任务批次、技能演进、任务连续性、工具搜索、项目摘要、对话引用和浏览器控制。新增层负责数据和任务状态，每节点独立执行。

- **正式数据源**：SGM定制接口已真实取数，完整窗口111篇、3页，原始字段与覆盖率保留。CMC的ES/通用业务桥接尚缺正式配置。
- **视频证据**：SGM的SIS已真实调用并保存任务、转写和终态失败。26篇降级中21篇无转写结果、5篇下载失败，按旧worker的 fallback-to-source 策略使用现有标题正文；文章和报告明确区分降级与成功转写。
- **外部功能**：外部RAG、其它MCP服务、图片/语音供应商与消息渠道仍需各自配置；已开放原生入口和可运行功能。此次数据库查询通过DeerFlow原生ModelTool实现，未另建对外MCP服务器。
- **沙箱**：已验证 DeerFlow 本地文件沙箱；本机 `allow_host_bash=false`。远程云沙箱和真实脚本执行需配置上游支持的 SandboxProvider，尚未部署或验收。
- **消息推送**：仅保存预览，没有发送钉钉或其他外部消息。CMC 的六个固定时点、150分钟入库窗口、09:00–20:00定时推送限制和历史回放禁发已落实到策略。
- **批量与权限**：SGM按最多12篇/100KB分批，批次结果与原生thread/run持久保存；合流目前以批次节点完成为边界，尚非逐篇文章贯穿全图的流式执行。其他Agent节点仍有200KB上限。交互执行绑定发起者，后台PAT仅配置本机主账号，跨账号无人值守任务需各自授权。Word提供可编辑正文与表格，图表另存HTML/SVG。原生会话查询后按团队过滤，跨团队记录较多时可能短页。
- **报告范围**：本次只验证五分钟入库数据。报告复现参考案例的结构与问数链路，未据此编造七日增长、全网覆盖、机器人或影响力结论。

## 开发与维护

依赖：Python3.12、Node22+、pnpm10.26.2、MySQL、Redis。当前本机依赖已经安装。

```powershell
# 改动扩展后，停止 Gateway 再升级（管理器负责锁文件）
./scripts/dev/stop-local.ps1
./scripts/dev/install-extension.ps1
./scripts/dev/start-local.ps1

# 后端测试；验证项目与现有业务数据隔离
$env:PYTHONUTF8='1'
$env:PYTHONPATH='extensions/ace'
.venv/Scripts/python.exe -m pytest extensions/ace/tests --mysql -q
.venv/Scripts/python.exe scripts/verify/baseline.py

# 前端检查
Push-Location extensions/ace/ui
pnpm build
pnpm test
Pop-Location
```

首次在另一台机器安装：按上游说明安装 `deer-flow/backend` 与 `frontend` 依赖；创建根 `.venv` 并安装测试依赖 `uv sqlalchemy pymysql redis pydantic-settings croniter httpx pytest pytest-asyncio ruff python-docx` 和上游本地 `deerflow-extension-api` 包；复制 `.env.example` 为根 `.env`；执行扩展安装脚本，再启动 Gateway，用原生注册/登录流程创建用户并签发 PAT。本机初始化脚本仅用于新环境，不会重置已有密码。

结构、节点映射和连接器协议见 `docs/ARCHITECTURE.md`、`docs/MIGRATION.md`、`docs/CONNECTORS.md`。
