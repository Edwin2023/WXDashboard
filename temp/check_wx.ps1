param([switch]$Kill)

$found = @()
$procs = Get-Process -Name wx,node -ErrorAction SilentlyContinue

foreach ($p in $procs) {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
    } catch { continue }
    if ($cmd -match 'wx-cli|wx\.js|jackwener|wx\.exe') {
        $found += $p
    }
}

if ($found.Count -eq 0) {
    Write-Host "OK - no wx-cli processes found" -ForegroundColor Green
} else {
    Write-Host "WARNING: $($found.Count) wx-cli process(es) found:" -ForegroundColor Yellow
    foreach ($p in $found) {
        Write-Host "  PID=$($p.Id)  Name=$($p.Name)  StartTime=$($p.StartTime)"
    }
    if ($Kill) {
        foreach ($p in $found) {
            Stop-Process -Id $p.Id -Force
            Write-Host "  Killed PID=$($p.Id)" -ForegroundColor Red
        }
        Write-Host "All wx-cli processes killed" -ForegroundColor Green
    } else {
        Write-Host "Run: .\temp\check_wx.ps1 -Kill   to force kill"
    }
}
