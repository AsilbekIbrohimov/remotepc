$tunnelProcess = $null

while ($true) {
    Write-Host "[$(Get-Date)] Tunnel boshlanmoqda..."

    $tunnelProcess = Start-Process -FilePath "ssh" -ArgumentList `
        "-o", "StrictHostKeyChecking=no", `
        "-o", "UserKnownHostsFile=nul", `
        "-R", "80:127.0.0.1:8765", `
        "serveo.net" `
        -NoNewWindow -PassThru -RedirectStandardOutput "C:\Temp\tunnel_output.txt"

    # Tunnel ulanishini kutamiz
    Start-Sleep -Seconds 3

    # URL ni konsolga yozamiz
    if (Test-Path "C:\Temp\tunnel_output.txt") {
        Get-Content "C:\Temp\tunnel_output.txt" | Select-String "Forwarding" | ForEach-Object {
            Write-Host $_.Line
        }
    }

    # Tunnel to'xtamasligini kutamiz
    $tunnelProcess.WaitForExit()

    Write-Host "[$(Get-Date)] Tunnel buzilib ketdi, qayta ulanmoqda..."
    Start-Sleep -Seconds 3
}
