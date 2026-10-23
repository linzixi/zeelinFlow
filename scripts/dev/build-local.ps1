<#
预构建日常使用的前端，避免页面切换触发开发编译；不启动服务、不读取模型密钥。
Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes
Requires: installed frontend dependencies; frontend port 3000 stopped
#>
param([ValidateRange(2048, 8192)][int]$HeapMegabytes = 3072)
$ErrorActionPreference = 'Stop'
$migrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) {
    throw '请先用 scripts/dev/stop-local.ps1 -Service frontend 停止前端，再构建。'
}
Push-Location (Join-Path $migrationRoot 'deer-flow/frontend')
try {
    & node "--max-old-space-size=$HeapMegabytes" './node_modules/next/dist/bin/next' build --webpack --experimental-debug-memory-usage
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败，退出码 $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath '.next/BUILD_ID')) { throw '构建没有生成 BUILD_ID。' }
    Write-Output '前端构建完成。运行 scripts/dev/start-local.ps1 启动。'
} finally {
    Pop-Location
}
