$dir = "C:\Users\Asilbek\OneDrive\Documents\remote"
$exe = "$dir\ngrok.exe"
$domain = "agent-habitat-launch.ngrok-free.dev"
while ($true) {
  $ok = $false
  try {
    $t = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3
    if ($t.tunnels.Count -gt 0) { $ok = $true }
  } catch {}
  if (-not $ok) {
    Get-Process -Name ngrok -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
    # Defender ba'zan ngrok.exe ni karantinga oladi — yo'q bo'lsa zip'dan tiklaymiz
    if (-not (Test-Path $exe)) {
      try { Expand-Archive -Path "$dir\ngrok.zip" -DestinationPath $dir -Force } catch {}
    }
    # Static domen bilan ishga tushiramiz (aks holda tasodifiy URL bo'ladi)
    Start-Process -FilePath $exe -ArgumentList "http","--url=$domain","8765" -WindowStyle Hidden
    Start-Sleep -Seconds 8
  }
  Start-Sleep -Seconds 10
}
