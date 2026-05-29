param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 7860,
    [string]$RunsRoot = "product_runs",
    [switch]$Restart,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$url = "http://$HostName`:$Port"

function Test-PythonModule($module) {
    & python -c "import $module" 2>$null
    return $LASTEXITCODE -eq 0
}

$connections = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue)
if ($connections.Count -gt 0) {
    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    if ($Restart) {
        foreach ($pidValue in $pids) {
            try { Stop-Process -Id $pidValue -Force -ErrorAction Stop } catch {}
        }
        Start-Sleep -Milliseconds 500
    } else {
        Write-Host "服务已经在运行：$url" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process $url }
        return
    }
}

if (-not (Test-PythonModule "flask")) {
    Write-Host "未检测到 Flask。请先安装依赖：python -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

if (-not $NoBrowser) {
    Start-Process $url
}

Write-Host "启动软件工坊：$url" -ForegroundColor Cyan
Write-Host "默认演示账号：showcase_admin / 12345678" -ForegroundColor DarkGray
Write-Host "按 Ctrl+C 可停止服务。" -ForegroundColor DarkGray
python -m agent.ui.app --host $HostName --port $Port --runs-root $RunsRoot
