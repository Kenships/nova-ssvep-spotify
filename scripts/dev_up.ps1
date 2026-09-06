# Launches simulator + backend + frontend together for local dev/demo.
# Each runs in its own PowerShell window so logs stay readable.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1
#        powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1 -DetectorBackend cca

param(
    [string]$DetectorBackend = "psda",
    [string]$SimFreq = ""
)

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$simulatorScript = Join-Path $root "simulator\mock_eeg_lsl.py"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Backend venv not found at $venvPython. Run: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$simArgs = @($simulatorScript)
if ($SimFreq -ne "") { $simArgs += @("--freq", $SimFreq) }

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$root`"; & `"$venvPython`" $($simArgs -join ' ')"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$backendDir`"; `$env:DETECTOR_BACKEND='$DetectorBackend'; & `"$venvPython`" -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$frontendDir`"; npm run dev"

Write-Host "Launched simulator, backend (detector=$DetectorBackend), and frontend in separate windows."
Write-Host "Frontend: http://localhost:5173"
