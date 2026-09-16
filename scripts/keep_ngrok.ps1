$exe = "C:\Users\Asilbek\OneDrive\Documents\remote\ngrok.exe"
while ($true) {
  $ok = $false
  try {
    $t = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3
    if ($t.tunnels.Count -gt 0) { $ok = $true }
  } catch {}
  if (-not $ok) {
    Get-Process -Name ngrok -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
    Start-Process -FilePath $exe -ArgumentList "http","8765","--region=in" -WindowStyle Hidden
    Start-Sleep -Seconds 8
  }
  Start-Sleep -Seconds 10
}
