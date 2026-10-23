<#
启动指定的本地 DeerFlow 服务，模型与 ACE 配置统一读取迁移根目录 .env。
Owner: ACE migration
Last verified: 2026-10-22
Idempotent: no (one foreground process per service)
Requires: installed native backend/frontend, local MySQL and Redis
#>
param(
    [ValidateSet('gateway', 'frontend')][string]$Service = 'gateway',
    [switch]$Development
)
$ErrorActionPreference = 'Stop'
$migrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:PYTHONUTF8 = '1'
$env:DEER_FLOW_HOME = Join-Path $migrationRoot '.runtime/deerflow'
$env:DEER_FLOW_ENV_FILE = Join-Path $migrationRoot '.env'
if ($Service -eq 'gateway') {
    Set-Location (Join-Path $migrationRoot 'deer-flow/backend')
    & './.venv/Scripts/python.exe' -m uvicorn app.gateway.app:app `
        --env-file $env:DEER_FLOW_ENV_FILE --host 127.0.0.1 --port 8001 --log-level warning
} else {
    Set-Location (Join-Path $migrationRoot 'deer-flow/frontend')
    if ($Development) {
        & node './node_modules/next/dist/bin/next' dev --webpack --hostname 127.0.0.1 --port 3000
    } else {
        if (-not (Test-Path -LiteralPath '.next/BUILD_ID')) {
            throw '请先运行 scripts/dev/build-local.ps1 生成前端正式构建。'
        }
        & node './node_modules/next/dist/bin/next' start --hostname 127.0.0.1 --port 3000
    }
}
exit $LASTEXITCODE
