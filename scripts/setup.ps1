# Remote PC Monitor — GitHub'dan tiklashdan keyin avtomat sozlash (Windows)
# Ishga tushirish:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
Write-Host "=== Remote PC Monitor — sozlash ===" -ForegroundColor Cyan

# Python topamiz
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" }
if (-not (Test-Path $py)) { Write-Host "Python topilmadi — python.org dan 3.12+ o'rnating" -ForegroundColor Red; exit 1 }
Write-Host "Python: $py"

# 1) Python paketlari
Write-Host "`n[1/5] Python paketlari o'rnatilmoqda..." -ForegroundColor Yellow
& $py -m pip install --upgrade pip -q
& $py -m pip install -r requirements.txt

# 2) cloudflared
Write-Host "`n[2/5] cloudflared..." -ForegroundColor Yellow
if (-not (Test-Path "$root\cloudflared.exe")) {
  try {
    Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$root\cloudflared.exe" -TimeoutSec 120
    Write-Host "  yuklandi"
  } catch { Write-Host "  YUKLANMADI — brauzerdan qo'lda yuklang (WARP yoqib): github.com/cloudflare/cloudflared/releases" -ForegroundColor Red }
} else { Write-Host "  bor" }

# 3) telegram-bot-api (lokal server, 2GB limit) — ixtiyoriy
Write-Host "`n[3/5] telegram-bot-api (lokal Bot API)..." -ForegroundColor Yellow
if (-not (Test-Path "$root\botapi\telegram-bot-api.exe")) {
  New-Item -ItemType Directory -Force "$root\botapi" | Out-Null
  try {
    Invoke-WebRequest "https://1111-releases... " -OutFile "$null" -TimeoutSec 1 2>$null
  } catch {}
  Write-Host "  QO'LDA: github.com/SwissCore92/telegram-bot-api-bin/releases -> windows-amd64.zip" -ForegroundColor Red
  Write-Host "  ichidagilarni botapi\ ga chiqaring. (USE_LOCAL_BOT_API=0 qilsangiz shart emas, limit 50MB)" -ForegroundColor DarkGray
} else { Write-Host "  bor" }

# 4) Papkalar
Write-Host "`n[4/5] Papkalar..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\RemotePC\dvr" | Out-Null
Write-Host "  DATA_DIR: $env:LOCALAPPDATA\RemotePC"

# 5) Avtomatik ishga tushirish (Startup)
Write-Host "`n[5/5] Startup (kompyuter yonganda avtomat)..." -ForegroundColor Yellow
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
Copy-Item "$root\scripts\startup.vbs" "$startup\TelegramPCMonitorBot.vbs" -Force
Write-Host "  startup.vbs o'rnatildi"

Write-Host "`n=== QOLGAN QO'LDA QADAMLAR ===" -ForegroundColor Cyan
Write-Host "1) .env.example -> .env deb nusxalab, tokenlarni to'ldiring (TG_BOT_TOKEN, TG_OWNER_ID, TG_API_ID, TG_API_HASH)"
Write-Host "2) Userbot (Saqlangan xabarlar/chatlar uchun): gifts_session.session faylini ko'chiring,"
Write-Host "   yoki Telethon bilan qayta login qiling (telefon + kod)."
Write-Host "3) Ishga tushirish:  startup.vbs ni ikki marta bosing (yoki kompyuterni qayta yoqing)"
Write-Host "`nTayyor!" -ForegroundColor Green
