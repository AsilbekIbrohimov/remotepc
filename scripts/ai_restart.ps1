Start-Sleep -Seconds 25
Get-Process -Name pythonw -ErrorAction SilentlyContinue | Where-Object {(Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -like '*monitor_bot*'} | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -FilePath 'C:\Users\Asilbek\AppData\Local\Programs\Python\Python314\pythonw.exe' -ArgumentList 'C:\Users\Asilbek\OneDrive\Documents\remote\monitor_bot.py' -WindowStyle Hidden
