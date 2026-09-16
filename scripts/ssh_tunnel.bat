@echo off
setlocal enabledelayedexpansion

:loop
echo [%date% %time%] SSH tunnel boshlanmoqda...
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=nul -R 80:127.0.0.1:8765 serveo.net
echo [%date% %time%] Tunnel buzilib ketdi, 3 soniyada qayta ulanadi...
timeout /t 3 /nobreak
goto loop
