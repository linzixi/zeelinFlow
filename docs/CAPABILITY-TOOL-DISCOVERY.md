# 能力中心的扩展算子目录

日期：2026-10-23

原能力中心已有“扩展”页，但扩展详情只显示标题、简介和部署启用状态，未展示扩展注册的模型工具。因此能在对话调用的 ACE 查询算子无法在能力中心按名称找到。

现入口：`/workspace/capabilities?tab=extensions&extension=qingbo.ace`。

扩展详情增加“扩展算子”：展示工具名称、描述、随扩展启用状态，以及可展开的参数定义。“扩展”页搜索同时匹配工具名称和描述。目录只展示声明，不执行工具、不查询文章、不修改权限或配置。

宿主通用 GET /api/plugins 接口增加可选 model_tools 字段，只投影已注册声明的 name、description、input_schema；保留认证与 private/no-store。前端保留对旧接口未提供该字段的兼容。不在宿主硬编码 ACE 的业务工具。

验证：接口补丁前两项新增测试因缺失 model_tools 失败，补丁后相关后端测试 64 passed；前端目录和 DOM 测试 11 passed；ESLint 和 TypeScript 检查通过。后端回归使用独立测试配置，避免本机 ACE 团队规则影响上游测试的虚拟账号，生产权限未改。运行中接口已确认 qingbo.ace 启用且包含 warehouse_query、project_review_queue。旧 ACE status/diff 保持不变，规模检查通过。

前端初次构建内存不足；本次使用 NODE_OPTIONS=--max-old-space-size=2048、CIRCLE_NODE_TOTAL=2 和 build-local.ps1 -HeapMegabytes 2048 完整构建成功，未跳过类型检查。服务恢复后，Playwright 确认两个算子显示且“查看参数”可展开 include_details 定义。截图：`.playwright-cli/page-2026-10-23T02-03-32-488Z.png`。
