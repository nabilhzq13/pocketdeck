# Start PocketDeck hidden when you sign in to Windows (and start it now).
#   .\autostart.ps1          turn on
#   .\autostart.ps1 -Off     turn off
# Easier: double-click autostart.bat
param([switch]$Off)
$link = Join-Path ([Environment]::GetFolderPath('Startup')) 'PocketDeck.lnk'
if ($Off) {
  Remove-Item $link -ErrorAction SilentlyContinue
  Write-Host 'PocketDeck will no longer start with Windows. Run stop.bat to stop it now.'
  return
}
if (-not (Test-Path (Join-Path $PSScriptRoot '.deps'))) {
  Write-Host 'Run start.bat once first, so PocketDeck can install what it needs.'
  return
}

# Find the same Python that start.bat uses, and its windowless twin pythonw.exe.
$code = 'import sys; print(sys.executable)'
$pythonw = $null
foreach ($try in @({ py -3 -c $code }, { python -c $code })) {
  try { $exe = & $try 2>$null } catch { continue }
  if ($LASTEXITCODE -eq 0 -and $exe) {
    $candidate = Join-Path (Split-Path $exe.Trim()) 'pythonw.exe'
    if (Test-Path $candidate) { $pythonw = $candidate; break }
  }
}
if (-not $pythonw) { Write-Host 'Python was not found. Run start.bat first.'; return }

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = $pythonw
$s.Arguments = '"' + (Join-Path $PSScriptRoot 'server.py') + '" --background'
$s.WorkingDirectory = $PSScriptRoot
$s.Description = 'PocketDeck server (runs hidden)'
$s.Save()
Start-Process $link
Write-Host 'PocketDeck now starts hidden with Windows, and it is running.'
Write-Host 'Pair a phone at http://localhost:8765/pair'
