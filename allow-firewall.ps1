# Run as administrator if your phone cannot reach PocketDeck.
# Opens TCP port 8765 to devices on your local network and on your Tailscale network
# (100.64.0.0/10, only your own signed-in devices), on every network type. Nothing else.
$port = 8765
$settings = Join-Path $PSScriptRoot 'settings.json'
if (Test-Path $settings) { $port = (Get-Content $settings -Raw | ConvertFrom-Json).port }
Remove-NetFirewallRule -DisplayName 'PocketDeck' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'PocketDeck' -Direction Inbound -Protocol TCP -LocalPort $port `
  -RemoteAddress LocalSubnet, '100.64.0.0/10' -Action Allow -Profile Any | Out-Null
Write-Host "PocketDeck can now be reached on port $port from your local network and Tailscale."
