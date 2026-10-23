<#
在后台启动两项本地服务；已有监听端口时跳过，不接管已有进程。
Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: run-local.ps1 dependencies and free ports 3000/8001
#>
param([switch]$Development)
$ErrorActionPreference = 'Stop'
$migrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $Development -and -not (Test-Path -LiteralPath (Join-Path $migrationRoot 'deer-flow/frontend/.next/BUILD_ID'))) {
    throw '请先运行 scripts/dev/build-local.ps1。日常启动使用预构建前端；仅开发调试加 -Development。'
}
$runtimeDir = Join-Path $migrationRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$shellPath = (Get-Process -Id $PID).Path
foreach ($service in @(@{name='gateway'; port=8001}, @{name='frontend'; port=3000})) {
    if (Get-NetTCPConnection -LocalPort $service.port -State Listen -ErrorAction SilentlyContinue) {
        Write-Output "$($service.name): port $($service.port) already listening; skipped."
        continue
    }
    $runnerPath = Join-Path $PSScriptRoot 'run-local.ps1'
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        ('"' + $runnerPath + '"'), '-Service', $service.name)
    if ($Development -and $service.name -eq 'frontend') { $arguments += '-Development' }
    $process = Start-Process -FilePath $shellPath -ArgumentList $arguments -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeDir "$($service.name).stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDir "$($service.name).stderr.log") -PassThru
    $process.Id | Set-Content (Join-Path $runtimeDir "$($service.name).pid") -Encoding utf8
    Write-Output "$($service.name): PID $($process.Id) starting."
}
Write-Output 'http://127.0.0.1:3000/workspace/projects'
