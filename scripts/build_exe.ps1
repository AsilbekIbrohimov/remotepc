# Remote PC Monitor - bitta o'rnatuvchi exe (iexpress + Python zip)
$ErrorActionPreference = "Stop"
$proj = "C:\Users\Asilbek\OneDrive\Documents\remote"
$work = "C:\Users\Asilbek\AppData\Local\Temp\remotepc_build"
$stage = "$work\stage"
$app = "$work\app"
$distDir = "$proj\dist"
$py = "C:\Users\Asilbek\AppData\Local\Programs\Python\Python314\python.exe"

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $stage, $app, $distDir | Out-Null

Write-Host "[1/5] Loyiha nusxalash..."
$xd = @("$proj\.git", "$proj\__pycache__", "$proj\bot\__pycache__", "$proj\webapp\__pycache__",
  "$proj\premiere", "$proj\media", "$proj\dvr", "$proj\_split", "$proj\.claude", "$proj\dist", "$proj\scripts\__pycache__")
$xf = @("*.log", "*.mp4", "*.session", "*.session-journal", "web_url.txt", "access_grants.json",
  "subscribed_chats.json", "ngrok.exe", "ngrok.zip", "*.bak", "_ul", ".ai_session")
$rc = @($proj, $app, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
foreach ($d in $xd) { $rc += @("/XD", $d) }
foreach ($f in $xf) { $rc += @("/XF", $f) }
robocopy @rc | Out-Null
Write-Host "   webapp bor: $(Test-Path "$app\webapp\app.py"), scripts bor: $(Test-Path "$app\scripts\setup.ps1")"

Write-Host "[2/5] project.zip (Python, tez)..."
$pyzip = "import zipfile,os; z=zipfile.ZipFile(r'$stage\project.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6); base=r'$app'; [z.write(os.path.join(rt,f), os.path.relpath(os.path.join(rt,f),base)) for rt,ds,fs in os.walk(base) for f in fs]; z.close(); print('ok')"
& $py -c $pyzip
$zipMB = [math]::Round((Get-Item "$stage\project.zip").Length / 1MB, 1)
Write-Host "   project.zip = $zipMB MB"

Write-Host "[3/5] install.cmd..."
$installCmd = @'
@echo off
title Remote PC Monitor - o'rnatish
set DEST=%LOCALAPPDATA%\RemotePC\app
echo Fayllar chiqarilmoqda...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%~dp0project.zip' -DestinationPath '%DEST%' -Force"
echo Sozlanmoqda (Python, paketlar, autostart)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\scripts\setup.ps1"
echo.
echo === Tayyor! Bu oynani yopishingiz mumkin. ===
pause
'@
Set-Content "$stage\install.cmd" $installCmd -Encoding ascii

Write-Host "[4/5] SED..."
$exe = "$distDir\RemotePC_Setup.exe"
Remove-Item $exe -Force -ErrorAction SilentlyContinue
$sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=Remote PC Monitor ornatildi.
TargetName=$exe
FriendlyName=Remote PC Monitor Setup
AppLaunched=cmd.exe /c install.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0=install.cmd
FILE1=project.zip
[SourceFiles]
SourceFiles0=$stage
[SourceFiles0]
%FILE0%=
%FILE1%=
"@
$sedPath = "$work\build.sed"
Set-Content $sedPath $sed -Encoding ascii

Write-Host "[5/5] iexpress..."
Start-Process "$env:WINDIR\System32\iexpress.exe" -ArgumentList "/N", "/Q", "/M", $sedPath -Wait
if (Test-Path $exe) {
  $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
  Write-Host "TAYYOR: $exe ($mb MB)" -ForegroundColor Green
} else { Write-Host "EXE yaratilmadi" -ForegroundColor Red }
