# Starts the whole app end-to-end: simulator + backend + frontend, each in
# its own PowerShell window, then opens the player in a browser.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1
#        powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1 -DetectorBackend cca
#        powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1 -SimFreq 10.0
#
# Run scripts/dev_down.ps1 to stop everything cleanly afterward.
#
# Note on quoting: every path here that might contain spaces (this repo
# lives under "NOVA buildathon 2026") is passed to the child PowerShell via
# -WorkingDirectory or wrapped in SINGLE quotes inside the -Command string,
# never embedded double quotes -- Start-Process's -ArgumentList does not
# reliably preserve literal `"` characters embedded inside a command
# string across the process-creation boundary (confirmed by testing: a
# `cd "<path>"` built that way silently no-ops, leaving the child in the
# wrong directory with no visible error).

param(
    [string]$DetectorBackend = "psda",
    [string]$SimFreq = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$simulatorScript = Join-Path $root "simulator\mock_eeg_lsl.py"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$frontendPort = 5173
$backendPort = 8000

function Stop-PortListener {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        Write-Host "Port $Port is in use by PID $($conn.OwningProcess) -- stopping it."
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Stop-MatchingPythonProcesses {
    # See the matching function in dev_down.ps1 for why this also walks
    # ParentProcessId: uvicorn --reload's actual worker is a multiprocessing
    # child on Windows whose own command line never mentions "uvicorn", and
    # whoever Get-NetTCPConnection blames for the socket isn't reliably the
    # process that's actually still serving requests.
    param([string]$Pattern)
    $all = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    $matched = $all | Where-Object { $_.CommandLine -like $Pattern }
    $matchedIds = $matched | ForEach-Object { $_.ProcessId }
    $children = $all | Where-Object { $matchedIds -contains $_.ParentProcessId }
    @($matched) + @($children) | Sort-Object ProcessId -Unique |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# --- Preflight ---

if (-not (Test-Path $venvPython)) {
    Write-Error "Backend venv not found at $venvPython.`nRun: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "frontend/node_modules not found -- running npm install first (one-time)..."
    Push-Location $frontendDir
    try { npm install } finally { Pop-Location }
}

if (-not (Test-Path (Join-Path $backendDir ".env"))) {
    Write-Warning "backend/.env not found -- copying .env.example. Fill in Spotify credentials there if you want that part working."
    Copy-Item (Join-Path $root ".env.example") (Join-Path $backendDir ".env")
}

# Stray processes from a previous crashed/killed run are the single most
# common cause of "port already in use" or file-locked errors here -- clear
# them before starting rather than after something fails.
Stop-MatchingPythonProcesses -Pattern "*uvicorn*"
Stop-MatchingPythonProcesses -Pattern "*mock_eeg_lsl.py*"
Stop-PortListener -Port $backendPort
Stop-PortListener -Port $frontendPort

# --- Launch ---
# Each child uses -WorkingDirectory (not an embedded `cd "..."`) and single
# quotes around any path inside its -Command string -- see note above.

$simCommand = "& '$venvPython' '$simulatorScript'"
if ($SimFreq -ne "") { $simCommand += " --freq $SimFreq" }
Start-Process powershell -ArgumentList "-NoExit", "-Command", $simCommand -WorkingDirectory $root

$backendCommand = "`$env:DETECTOR_BACKEND='$DetectorBackend'; & '$venvPython' -m uvicorn app.main:app --reload --port $backendPort"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCommand -WorkingDirectory $backendDir

$frontendCommand = "npx vite --port $frontendPort"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCommand -WorkingDirectory $frontendDir

Write-Host ""
Write-Host "Launched simulator, backend (detector=$DetectorBackend), and frontend in separate windows."
Write-Host "Run scripts/dev_down.ps1 when you're done to stop everything cleanly."

# Give the frontend dev server a moment to come up before opening it.
Start-Sleep -Seconds 3
Start-Process "http://localhost:$frontendPort"
