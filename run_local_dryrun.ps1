param(
    [string]$ReportDate = "",
    [string]$Model = "gpt-5.5",
    [string]$BaseUrl = "https://ai.860812.xyz",
    [string]$ApiKey = "",
    [string]$Timezone = "Asia/Shanghai"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$secretScript = Join-Path $scriptDir "run_local.secrets.ps1"
if (Test-Path $secretScript) {
    . $secretScript
}

if (-not $ApiKey) {
    $ApiKey = $env:OPENAI_API_KEY
}

if (-not $ApiKey) {
    throw "Missing API key. Pass -ApiKey or set `$env:OPENAI_API_KEY, or create ignored file run_local.secrets.ps1."
}

$pythonExe = $null
# 优先使用系统 Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $pythonExe = $pythonCmd.Source
}
# 备选：Codex 内置 Python
if (-not $pythonExe) {
    $bundledPython = "C:\Users\AS\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $bundledPython) {
        $pythonExe = $bundledPython
    }
}

if (-not $pythonExe) {
    throw "Python not found. Install Python or restore the bundled Codex runtime."
}

$env:PYTHONIOENCODING = "utf-8"
$env:OPENAI_API_KEY = $ApiKey
$env:OPENAI_BASE_URL = $BaseUrl
$env:OPENAI_MODEL = $Model
$env:ENABLE_REMOTE_TRANSLATION = "1"
$env:ENGLISH_OUTPUT_MODE = "0"
$env:TZ = $Timezone

Remove-Item Env:FEISHU_WEBHOOK_URL -ErrorAction SilentlyContinue

$args = @("main.py", "--dry-run", "--debug", "--timezone", $Timezone)
if ($ReportDate) {
    $args += @("--date", $ReportDate)
}

Write-Host "Running local dry-run with model $Model ..." -ForegroundColor Cyan
& $pythonExe @args
if ($LASTEXITCODE -ne 0) {
    throw "Local dry-run failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Artifacts written to data/:" -ForegroundColor Green
Write-Host "  - last_report.md"
Write-Host "  - last_card.json"
Write-Host "  - raw_candidates.json"
Write-Host "  - filtered_candidates.json"
Write-Host "  - scored_candidates.json"
Write-Host "  - final_selected.json"
Write-Host "  - quality_errors.json"
