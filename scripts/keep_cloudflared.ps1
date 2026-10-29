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
  # --protocol http2: UDP/QUIC bloklangan tarmoqlarda ishonchli (ISP UDP'ni to'sadi)
  Start-Process -FilePath $exe -WindowStyle Hidden `
    -ArgumentList 'tunnel','--url','http://localhost:8765','--no-autoupdate','--protocol','http2' `
    -RedirectStandardError $log -RedirectStandardOutput "$dir\cloudflared_out.log"

  # trycloudflare havolasini kutamiz
  # Diqqat: 'api.trycloudflare.com' - bu cloudflared murojaat qiladigan manzil, bizning havola EMAS.
  # Shuning uchun kamida bitta chiziqcha talab qilamiz va 'api.' ni chiqarib tashlaymiz.
  $pat = 'https://(?!api\.)[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com'
  $url = $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $log) {
      $m = Select-String -Path $log -Pattern $pat -AllMatches | Select-Object -Last 1
      if ($m) { $url = $m.Matches[0].Value; break }
    }
  }
  if ($url) {
    Set-Content -Path $urlfile -Value $url -Encoding ascii -NoNewline
  }

  # cloudflared tirik ekan kutamiz, LEKIN tunnel sog'ligini ham kuzatamiz:
  # quick tunnel muddati tugasa jarayon tirik qoladi-yu, log'da
  # "Tunnel not found" aylanishi boshlanadi - bunda o'zimiz o'ldirib, yangi tunnel olamiz.
  while (Get-Process cloudflared -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 15
    $tail = Get-Content $log -Tail 25 -ErrorAction SilentlyContinue
    if ($tail) {
      $bad = $tail | Select-String -Pattern 'Tunnel not found|Register tunnel error' -Quiet
      $ok = $tail | Select-String -Pattern 'Registered tunnel connection' -Quiet
      if ($bad -and -not $ok) {
        # tunnel o'lgan - jarayonni o'ldiramiz, tashqi tsikl yangi havola oladi
        Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
        break
      }
    }
  }
}
