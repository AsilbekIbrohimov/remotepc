# Remote PC Monitor — GitHub'dan tiklashdan keyin TO'LIQ avtomat sozlash (Windows)
# Ishga tushirish:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
Write-Host "=== Remote PC Monitor — sozlash ===" -ForegroundColor Cyan
Write-Host "Loyiha: $root"

# --- Python topish (qattiq kodsiz) ---
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
  $cand = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($cand) { $py = $cand.FullName }
}
if (-not $py -or -not (Test-Path $py)) { Write-Host "Python topilmadi — python.org dan 3.12+ o'rnating, keyin qayta ishga tushiring" -ForegroundColor Red; exit 1 }
$pyw = $py -replace 'python\.exe$', 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
Write-Host "Python: $py"

# --- 1) Paketlar ---
Write-Host "`n[1/6] Python paketlari..." -ForegroundColor Yellow
& $py -m pip install --upgrade pip -q
& $py -m pip install -r requirements.txt

# --- 2) cloudflared ---
Write-Host "`n[2/6] cloudflared (tunnel)..." -ForegroundColor Yellow
if (-not (Test-Path "$root\cloudflared.exe")) {
  try {
    Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$root\cloudflared.exe" -TimeoutSec 180
    Write-Host "  yuklandi"
  } catch { Write-Host "  YUKLANMADI (WARP yoqib qayta urining yoki brauzerdan): github.com/cloudflare/cloudflared/releases" -ForegroundColor Red }
} else { Write-Host "  bor" }

# --- 3) telegram-bot-api (lokal server, 2GB) ---
Write-Host "`n[3/6] telegram-bot-api (2GB limit)..." -ForegroundColor Yellow
if (-not (Test-Path "$root\botapi\telegram-bot-api.exe")) {
  New-Item -ItemType Directory -Force "$root\botapi" | Out-Null
  try {
    $rel = Invoke-RestMethod "https://api.github.com/repos/SwissCore92/telegram-bot-api-bin/releases/latest" -Headers @{ "User-Agent" = "ps" } -TimeoutSec 60
    $asset = $rel.assets | Where-Object { $_.name -match 'windows-amd64\.zip$' } | Select-Object -First 1
    if ($asset) {
      $zip = "$env:TEMP\tba.zip"
      Invoke-WebRequest $asset.browser_download_url -OutFile $zip -TimeoutSec 180
      Expand-Archive $zip "$root\botapi" -Force
      Remove-Item $zip -Force
      Write-Host "  yuklandi va chiqarildi"
    } else { throw "asset topilmadi" }
  } catch {
    Write-Host "  YUKLANMADI (WARP yoqib qayta urining yoki qo'lda): github.com/SwissCore92/telegram-bot-api-bin/releases" -ForegroundColor Red
    Write-Host "  (yoki .env da USE_LOCAL_BOT_API=0 -> 50MB limit, botapi shart emas)" -ForegroundColor DarkGray
  }
} else { Write-Host "  bor" }

# --- 4) Papkalar ---
Write-Host "`n[4/6] Papkalar..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\RemotePC\dvr" | Out-Null

# --- 5) startup.vbs ni SHU mashina yo'llari bilan yaratish ---
Write-Host "`n[5/6] Avtostart (yo'llar shu mashinaga moslanadi)..." -ForegroundColor Yellow
$vbs = @"
' Remote PC Monitor - oynasiz avtostart (setup.ps1 yaratgan)
Set sh = CreateObject("WScript.Shell")
base = "$root\"
py = "$pyw"
sh.CurrentDirectory = base
sh.Run "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & base & "scripts\keep_botapi.ps1""", 0, False
sh.Run """" & py & """ """ & base & "web_server.py""", 0, False
WScript.Sleep 10000
sh.Run """" & py & """ """ & base & "monitor_bot.py""", 0, False
sh.Run "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & base & "scripts\keep_cloudflared.ps1""", 0, False
"@
$startupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$vbsPath = "$startupDir\TelegramPCMonitorBot.vbs"
Set-Content -Path $vbsPath -Value $vbs -Encoding ascii
# keep_botapi / keep_cloudflared skriptlaridagi yo'llarni ham shu mashinaga moslaymiz
foreach ($f in @("$root\scripts\keep_botapi.ps1", "$root\scripts\keep_cloudflared.ps1")) {
  if (Test-Path $f) {
    (Get-Content $f -Raw) -replace 'C:\\Users\\Asilbek\\OneDrive\\Documents\\remote', $root.Replace('\','\\') | Set-Content $f -Encoding utf8
  }
}
Write-Host "  startup.vbs o'rnatildi: $vbsPath"

# --- 6) Hozir ishga tushirish ---
Write-Host "`n[6/6] Ishga tushirish..." -ForegroundColor Yellow
if (Test-Path "$root\.env") {
  Start-Process "wscript.exe" $vbsPath
  Write-Host "  ishga tushirildi (~30-60s da tayyor bo'ladi)"
} else {
  Write-Host "  .env YO'Q — avval .env.example dan nusxalab to'ldiring, keyin vbs ni bosing" -ForegroundColor Red
}

Write-Host "`n=== TAYYOR ===" -ForegroundColor Green
Write-Host "Telegram'da botga /start -> menyu tugmasidan (chat pastidagi) Mini App."
Write-Host "Qolgani (ixtiyoriy): userbot uchun gifts_session.session ni ko'chiring."
