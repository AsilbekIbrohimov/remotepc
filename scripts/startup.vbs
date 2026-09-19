' Telegram PC Monitor - barcha komponentlarni OYNASIZ ishga tushiradi
' (CMD/PowerShell oynalari umuman chiqmaydi - window style 0 = hidden)
Set sh = CreateObject("WScript.Shell")
base = "C:\Users\Asilbek\OneDrive\Documents\remote\"
py = "C:\Users\Asilbek\AppData\Local\Programs\Python\Python314\pythonw.exe"
sh.CurrentDirectory = base

' 1) Lokal Bot API server watcher (2GB fayl limiti) - botdan oldin
sh.Run "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & base & "scripts\keep_botapi.ps1""", 0, False

' 2) Web server (Mini App)
sh.Run """" & py & """ """ & base & "web_server.py""", 0, False

' 3) Bot API server ko'tarilishi uchun kutamiz
WScript.Sleep 10000

' 4) Bot
sh.Run """" & py & """ """ & base & "monitor_bot.py""", 0, False

' 5) ngrok tunnel watcher
sh.Run "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & base & "scripts\keep_ngrok.ps1""", 0, False
