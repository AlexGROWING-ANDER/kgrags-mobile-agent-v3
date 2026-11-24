param(
    [Parameter(Mandatory = $true)]
    [int]$PreflightPid,

    [Parameter(Mandatory = $true)]
    [string]$PreflightBatch
)

$ErrorActionPreference = "Stop"

$python = "D:\Users\Anaconda\anaconda3\envs\my_env\python.exe"
$adb = "D:\Android\platform-tools\adb.exe"
$projectDir = "C:\Users\ASUS\Documents\Codex\2026-09-19\new-chat\mobile_agent_v3\mobile_v3"
$runner = Join-Path $projectDir "run_batch.py"
$config = Join-Path $projectDir "experiments_hard_intents.json"
$logRoot = "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\logs"
$launcherRoot = "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2"

$checkpoints = @(
    "E:\GUI_AGENT_runs\mobile_agent_v3\logs_130_resume\batch_20260923_015703\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\logs_60\batch_20260923_003437\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\precheck_fixed\batch_20260922_210543\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\precheck_gui_fixed\batch_20260922_210718\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\precheck_logs\batch_20260922_202540\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\logs\batch_20260925_172345\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\logs\batch_20260927_121325\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\logs\batch_20260927_230359\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\logs\batch_20260928_131858\summary.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\chainhome_test1_checkpoint.json",
    "E:\GUI_AGENT_runs\mobile_agent_v3\retry_20260925_failure_v2\logs\batch_20260928_133213\summary.json"
)

$preflightProcess = Get-Process -Id $PreflightPid -ErrorAction SilentlyContinue
if ($preflightProcess) {
    Wait-Process -Id $PreflightPid
}
Start-Sleep -Seconds 2

$preflightSummary = Join-Path $PreflightBatch "summary.json"
if (-not (Test-Path -LiteralPath $preflightSummary)) {
    throw "Preflight ended without summary.json: $preflightSummary"
}

$summary = Get-Content -Raw -Encoding UTF8 -LiteralPath $preflightSummary | ConvertFrom-Json
if ($summary.completed -ne 1 -or $summary.error -ne 0) {
    throw "Preflight did not complete cleanly; the continuation was not started."
}

$allowedStatuses = @("success", "step_limit", "human_confirmation")
if ($summary.results.Count -ne 1 -or $summary.results[0].status -notin $allowedStatuses) {
    throw "Preflight status is not terminal and usable: $($summary.results[0].status)"
}

$adbOutput = & $adb devices
if (-not ($adbOutput -match "\sdevice\s*$")) {
    throw "No authorized ADB device is online."
}

$activeRunner = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match "mobile_v3[\\/]run_batch\.py" }
if ($activeRunner) {
    throw "Another Mobile-Agent batch is already running: $($activeRunner.ProcessId -join ',')"
}

$checkpoints += $preflightSummary
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdout = Join-Path $launcherRoot "continue_guarded_remaining_${stamp}.stdout.log"
$stderr = Join-Path $launcherRoot "continue_guarded_remaining_${stamp}.stderr.log"

$arguments = @(
    "-u", "-X", "utf8", $runner,
    "--config", $config,
    "--adb_path", $adb,
    "--coor_type", "abs",
    "--no-notetaker",
    "--max_step", "30",
    "--step_interval", "5",
    "--max_tasks", "50",
    "--max_consecutive_errors", "2",
    "--min_free_gb", "3",
    "--log_base", $logRoot
)
foreach ($checkpoint in $checkpoints) {
    $arguments += @("--resume_from", $checkpoint)
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Remove-Item Env:MOBILE_AGENT_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:MOBILE_AGENT_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:MOBILE_AGENT_MODEL -ErrorAction SilentlyContinue
Remove-Item Env:MOBILE_AGENT_LOG_BASE -ErrorAction SilentlyContinue

$process = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $projectDir `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

Write-Output "CONTINUATION_PID=$($process.Id)"
Write-Output "CONTINUATION_STDOUT=$stdout"
Write-Output "CONTINUATION_STDERR=$stderr"
