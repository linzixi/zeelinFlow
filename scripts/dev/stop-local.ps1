<#
只停止 start-local.ps1 记录且命令行归属匹配的本工程进程树。
Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: Windows CIM, .runtime PID files
#>
param([ValidateSet('all', 'gateway', 'frontend')][string]$Service = 'all')
$ErrorActionPreference = 'Stop'
$migrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runnerPath = Join-Path $PSScriptRoot 'run-local.ps1'
foreach ($serviceName in @('gateway', 'frontend')) {
    if ($Service -ne 'all' -and $serviceName -ne $Service) { continue }
    $pidFile = Join-Path $migrationRoot ".runtime/$serviceName.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $servicePid = [int](Get-Content -LiteralPath $pidFile)
    $rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid"
    if (-not $rootProcess) { continue }
    if (-not $rootProcess.CommandLine.Contains($runnerPath)) {
        throw "PID ownership mismatch: $serviceName"
    }
    $allProcesses = @(Get-CimInstance Win32_Process)
    $descendants = [System.Collections.Generic.List[int]]::new()
    $descendants.Add($servicePid)
    for ($index = 0; $index -lt $descendants.Count; $index++) {
        $parentPid = $descendants[$index]
        foreach ($child in $allProcesses | Where-Object ParentProcessId -eq $parentPid) {
            $descendants.Add([int]$child.ProcessId)
        }
    }
    for ($index = $descendants.Count - 1; $index -ge 0; $index--) {
        Stop-Process -Id $descendants[$index] -ErrorAction SilentlyContinue
    }
    Write-Output "$serviceName stopped; unfinished tasks recover through database leases."
}
