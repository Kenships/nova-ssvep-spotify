# Stops everything dev_up.ps1 started: the backend (port 8000, plus its
# --reload watcher/worker process pair -- see note below), the frontend
# dev server (port 5173), and any simulator process.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/dev_down.ps1

$backendPort = 8000
$frontendPort = 5173

function Stop-PortListener {
    param([int]$Port, [string]$Label)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "$Label (port $Port): nothing running."
        return
    }
    foreach ($conn in $conns) {
        Write-Host "$Label (port $Port): stopping PID $($conn.OwningProcess)."
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Stop-MatchingPythonProcesses {
    # Kills every python.exe whose command line matches $Pattern, PLUS any
    # python.exe child of one of those (by WMI ParentProcessId). This
    # matters because uvicorn --reload spawns its actual worker as a
    # multiprocessing child on Windows -- that child's own command line is
    # just a generic "multiprocessing.spawn spawn_main(...)" string with no
    # mention of uvicorn, so it won't match $Pattern directly, and
    # Get-NetTCPConnection can report the (already-dead) parent as the
    # socket's owner rather than the child that's actually still serving --
    # confirmed by testing: killing only the reported port-owner PID left a
    # live, responding server behind. Walking ParentProcessId catches it.
    param([string]$Pattern, [string]$Label)
    $all = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    $matched = $all | Where-Object { $_.CommandLine -like $Pattern }
    $matchedIds = $matched | ForEach-Object { $_.ProcessId }
    $children = $all | Where-Object { $matchedIds -contains $_.ParentProcessId }
    $toKill = @($matched) + @($children) | Sort-Object ProcessId -Unique

    if (-not $toKill) {
        Write-Host "$Label`: nothing running."
        return
    }
    foreach ($p in $toKill) {
        Write-Host "$Label`: stopping PID $($p.ProcessId)."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Stop-MatchingPythonProcesses -Pattern "*uvicorn*" -Label "Backend"
Stop-MatchingPythonProcesses -Pattern "*mock_eeg_lsl.py*" -Label "Simulator"
Stop-PortListener -Port $frontendPort -Label "Frontend"

# Catch-all: if anything is still somehow listening on the backend port
# after the above (e.g. a process this script's patterns didn't predict),
# stop it too rather than leave a silently-broken "port in use" state.
Stop-PortListener -Port $backendPort -Label "Backend (leftover)"

Write-Host "Done."
