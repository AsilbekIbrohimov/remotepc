@echo off
setlocal enabledelayedexpansion

:loop
echo [%date% %time%] Starting SSH tunnel to serveo.net...
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=nul -R 80:127.0.0.1:8765 serveo.net
echo [%date% %time%] Tunnel disconnected, reconnecting in 5 seconds...
timeout /t 5 /nobreak
goto loop
