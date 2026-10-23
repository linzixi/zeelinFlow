<#
构建并通过 DeerFlow 原生管理器安装/升级 ACE 扩展。
Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: pnpm, native backend environment, root uv environment; stop Gateway first
#>
$ErrorActionPreference = 'Stop'
$migrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:PYTHONUTF8 = '1'
$env:UV_LINK_MODE = 'copy'
$env:PATH = (Join-Path $migrationRoot '.venv/Scripts') + ';' + $env:PATH
Push-Location (Join-Path $migrationRoot 'extensions/ace/ui')
try {
    & pnpm install --frozen-lockfile
    if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' }
    & pnpm build
    if ($LASTEXITCODE) { throw 'Frontend build failed.' }
} finally { Pop-Location }
$nativePython = Join-Path $migrationRoot 'deer-flow/backend/.venv/Scripts/python.exe'
& $nativePython (Join-Path $PSScriptRoot 'configure_local.py')
if ($LASTEXITCODE) { throw 'Configuration staging failed.' }
Push-Location (Join-Path $migrationRoot 'deer-flow/backend')
try {
    $action = if (Select-String -LiteralPath 'pyproject.toml' -Pattern 'deerflow-extension-ace' -Quiet) {
        'upgrade'
    } else { 'install' }
    & './.venv/Scripts/deerflow.exe' extensions $action `
        (Join-Path $migrationRoot '.runtime/extension-source') --yes
    if ($LASTEXITCODE) { throw 'Native extension installation failed.' }
    & (Join-Path $migrationRoot '.venv/Scripts/uv.exe') sync --locked --all-packages --extra browser `
        --reinstall-package deerflow-extension-ace
    if ($LASTEXITCODE) { throw 'Extension wheel refresh failed.' }
} finally { Pop-Location }
