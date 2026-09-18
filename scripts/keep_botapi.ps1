# Lokal Telegram Bot API serverini ishga tushiradi va tirik tutadi (2GB fayl limiti)
$ErrorActionPreference = "SilentlyContinue"
$dir = "C:\Users\Asilbek\OneDrive\Documents\remote"
$exe = "$dir\botapi\telegram-bot-api.exe"
$data = "$dir\botapi\data"
New-Item -ItemType Directory -Force -Path $data | Out-Null

# .env dan api_id / api_hash o'qiymiz
$apiId = ""; $apiHash = ""
foreach ($line in Get-Content "$dir\.env") {
  if ($line -match '^\s*TG_API_ID\s*=\s*(.+?)\s*$')   { $apiId = $matches[1].Trim().Trim("'").Trim('"') }
  if ($line -match '^\s*TG_API_HASH\s*=\s*(.+?)\s*$')  { $apiHash = $matches[1].Trim().Trim("'").Trim('"') }
}
if (-not $apiId -or -not $apiHash) { Write-Output "api_id/api_hash topilmadi"; exit 1 }

while ($true) {
  $alive = $false
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:8081" -TimeoutSec 3 -UseBasicParsing
    $alive = $true
  } catch {
    # 404/boshqa javob ham server tirikligini bildiradi
    if ($_.Exception.Response) { $alive = $true }
  }
  if (-not $alive) {
    Get-Process -Name telegram-bot-api -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    Start-Process -FilePath $exe -WindowStyle Hidden -ArgumentList @(
      "--api-id=$apiId", "--api-hash=$apiHash", "--local",
      "--http-port=8081", "--dir=$data", "--log=$dir\botapi\botapi.log"
    )
    Start-Sleep -Seconds 6
  }
  Start-Sleep -Seconds 10
}
