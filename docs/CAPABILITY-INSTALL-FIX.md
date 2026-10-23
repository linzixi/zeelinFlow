# 能力安装 500 修复（2026-10-23）

## 普通用户安装钉钉

`POST /api/capabilities/installations` 在 `scope=user` 且账号不是平台管理员时，进入 `personal_mcp._validate_personal_server`。内置 stdio 能力检查直接读取 `server.cwd`，但 `McpServerConfigResponse` 只允许它作为可选扩展字段，不保证存在；正常钉钉配置未传该字段，触发 AttributeError，返回500。

改为读取可选字段 `getattr(server, "cwd", None)`。命令、参数、凭据字段的内置启动器校验继续执行；显式指定非空工作目录仍被拒绝，未放开普通用户任意宿主命令权限。管理员路径之前正常，因此回归必须使用普通用户。

## 能力中心 Windows 状态查询

飞书状态查询使用 `whoami /user /fo csv /nh` 解析当前 Windows 用户 SID。本机用户名包含中文，系统命令输出采用本地代码页，而 Python UTF-8 模式按 UTF-8 解码，读取线程异常后 stdout 为 None，继而触发 strip 异常。

SID 为 ASCII，只需要 CSV 第二列；现在显式使用 ASCII 并替换非 ASCII 字节，忽略不参与授权的显示名称。保留原有 SID 校验和 Windows 私有凭据 ACL 行为，不降低文件权限。

## 验证

- 先复现再修复：普通用户真实安装返回500、管理员返回200；新增普通用户钉钉/企业微信/HubSpot回归在修复前失败。
- 57项相关测试通过，覆盖能力安装、同名冲突、凭据脱敏、用户隔离、非空工作目录拒绝、个人 MCP、GBK/UTF-8/CP1252用户输出解析。原有 `.cmd` CLI 编码测试需在与其 `mbcs` 文件一致的代码页936下运行，4项全部通过；生产启动设置未改。
- Gateway重启后，经 `http://127.0.0.1:3000` 普通用户安装钉钉、读取个人安装列表、删除验证配置均200；飞书状态查询200。
- 使用无效占位凭据只验证保存链路，没有调用任何消息发送接口，不代表真实钉钉投递验证。未使用或复制聊天中的真实密钥到源码或文档。
- 证据：`output/verification/capability-install-fix.json`。验证配置已清理，旧ACE未改动，不提交仓库。
