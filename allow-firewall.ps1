# Run as administrator if your phone cannot reach PocketDeck.
# Opens TCP port 8765 for devices on your local network only (all network profiles).
$port = 8765
$settings = Join-Path $PSScriptRoot 'settings.json'
if (Test-Path $settings) { $port = (Get-Content $settings -Raw | ConvertFrom-Json).port }
Remove-NetFirewallRule -DisplayName 'PocketDeck' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'PocketDeck' -Direction Inbound -Protocol TCP -LocalPort $port `
  -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
Write-Host "PocketDeck can now be reached on port $port from your local network."
