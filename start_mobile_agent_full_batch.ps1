$ErrorActionPreference = "Stop"

$Python = "D:\Users\Anaconda\anaconda3\envs\my_env\python.exe"
$Adb = "D:\Android\platform-tools\adb.exe"
$ProjectDir = "C:\Users\ASUS\Documents\Codex\2026-09-19\new-chat\mobile_agent_v3\mobile_v3"
$Config = Join-Path $ProjectDir "experiments_hard_intents.json"
$LogRoot = "E:\GUI_AGENT_runs\mobile_agent_v3\logs"
$LauncherLogDir = "E:\GUI_AGENT_runs\mobile_agent_v3\launcher_logs"

foreach ($required in @($Python, $Adb, $Config)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path does not exist: $required"
    }
}

$adbOutput = & $Adb devices
if (-not ($adbOutput -match "\sdevice\s*$")) {
    throw "No authorized ADB device is online."
}

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LauncherLogDir -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdout = Join-Path $LauncherLogDir "full_batch_${stamp}.stdout.log"
$stderr = Join-Path $LauncherLogDir "full_batch_${stamp}.stderr.log"

$arguments = @(
    "-u",
    "run_batch.py",
    "--config", $Config,
    "--adb_path", $Adb,
    "--coor_type", "abs",
    "--max_step", "30",
    "--step_interval", "5",
    "--no-notetaker",
    "--min_free_gb", "2",
    "--log_base", $LogRoot
)

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectDir `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

Write-Output "PID=$($process.Id)"
Write-Output "STDOUT=$stdout"
Write-Output "STDERR=$stderr"
