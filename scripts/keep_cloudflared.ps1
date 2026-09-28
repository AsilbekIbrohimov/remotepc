# Cloudflare Tunnel (bepul, trafik limiti yo'q) — ishga tushiradi, havolani web_url.txt ga yozadi, tirik tutadi
$ErrorActionPreference = "SilentlyContinue"
$dir = "C:\Users\Asilbek\OneDrive\Documents\remote"
$exe = "$dir\cloudflared.exe"
$log = "$dir\cloudflared.log"
$urlfile = "$dir\web_url.txt"

while ($true) {
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 2
  Remove-Item $log -ErrorAction SilentlyContinue
  Start-Process -FilePath $exe -WindowStyle Hidden `
    -ArgumentList 'tunnel','--url','http://localhost:8765','--no-autoupdate' `
    -RedirectStandardError $log -RedirectStandardOutput "$dir\cloudflared_out.log"

  # trycloudflare havolasini kutamiz
  $url = $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $log) {
      $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
      if ($m) { $url = $m.Matches[0].Value; break }
    }
  }
  if ($url) {
    Set-Content -Path $urlfile -Value $url -Encoding ascii -NoNewline
  }

  # cloudflared tirik ekan kutamiz; o'lsa tsikl qaytadan (yangi havola)
  while (Get-Process cloudflared -ErrorAction SilentlyContinue) { Start-Sleep -Seconds 15 }
}
