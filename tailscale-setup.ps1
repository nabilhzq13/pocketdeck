# Make PocketDeck reachable on any network through Tailscale.
# Enables Tailscale "unattended" mode so the tunnel stays up without the app window open,
# brings it up now, starts it at every sign-in, and opens the firewall for Tailscale + LAN.
# Run as administrator (tailscale-setup.bat does this for you).
#   .\tailscale-setup.ps1          turn on
#   .\tailscale-setup.ps1 -Off     stop it starting at sign-in (tunnel stays as it is)

param([switch]$Off)

# Native tailscale.exe writes normal status to stderr; don't let that abort the script.
$ErrorActionPreference = 'Continue'
$ts  = 'C:\Program Files\Tailscale\tailscale.exe'
$gui = 'C:\Program Files\Tailscale\tailscale-ipn.exe'
$link = Join-Path ([Environment]::GetFolderPath('Startup')) 'Tailscale.lnk'

if (-not (Test-Path $ts)) {
  Write-Host 'Tailscale is not installed. Ask Claude to install it first.' -ForegroundColor Red
  return
}

if ($Off) {
  Remove-Item $link -ErrorAction SilentlyContinue
  Write-Host 'Tailscale will no longer start at sign-in. It stays connected until you quit it or reboot.'
  return
}

# 1. Stay connected without the app window open (survives closing the tray app).
cmd /c "`"$ts`" set --unattended" 2>$null | Out-Null
Write-Host 'Unattended mode on - the tunnel stays up on its own.'

# 2. Bring the tunnel up now (uses the login you already did; no browser unless it asks).
$up = cmd /c "`"$ts`" up --timeout=90s" 2>&1
$login = $up | Where-Object { $_ -match 'https://login' } | Select-Object -First 1
if ($login) { Write-Host "Sign in if asked: $login" -ForegroundColor Yellow }

# 3. Start Tailscale at every sign-in, so it reconnects after a reboot.
if (Test-Path $gui) {
  $shell = New-Object -ComObject WScript.Shell
  $s = $shell.CreateShortcut($link)
  $s.TargetPath = $gui
  $s.Description = 'Tailscale (keeps PocketDeck reachable anywhere)'
  $s.Save()
  Write-Host 'Tailscale will start automatically at sign-in.'
}

# 4. Let PocketDeck through the firewall for your LAN and your own Tailscale devices.
$port = 8765
$settings = Join-Path $PSScriptRoot 'settings.json'
if (Test-Path $settings) { $port = (Get-Content $settings -Raw | ConvertFrom-Json).port }
Remove-NetFirewallRule -DisplayName 'PocketDeck' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'PocketDeck' -Direction Inbound -Protocol TCP -LocalPort $port `
  -RemoteAddress LocalSubnet, '100.64.0.0/10' -Action Allow -Profile Any | Out-Null
Write-Host "Firewall opened for PocketDeck on port $port (LAN + Tailscale)."

# 5. Show the address to scan.
Start-Sleep -Seconds 1
$ip = (cmd /c "`"$ts`" ip -4" 2>$null | Select-Object -First 1)
Write-Host ''
if ($ip) {
  Write-Host "Done. This PC's Tailscale address is $ip" -ForegroundColor Green
  Write-Host "On the phone (with Tailscale installed and ON), open:  http://${ip}:$port"
  Write-Host "Or open the pairing page here and scan the Tailscale code:  http://localhost:$port/pair"
} else {
  Write-Host 'Tailscale is still connecting. Open the Tailscale app, make sure it says Connected,'
  Write-Host 'then open http://localhost:8765/pair to get the Tailscale code.' -ForegroundColor Yellow
}
