param([string]$Url = "http://localhost:8000/health", [int]$MaxSeconds = 60)

for ($i = 1; $i -le $MaxSeconds; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        Write-Host "  Backend ready after ${i}s"
        exit 0
    } catch {
        Write-Host "  ...${i}s"
        Start-Sleep 1
    }
}
Write-Host "ERROR: backend did not respond after ${MaxSeconds}s"
exit 1
