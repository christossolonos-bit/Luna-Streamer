# Creates a Desktop shortcut with icon (run once; shortcut stays on your PC).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Bat = Join-Path $Root "Open Luna Website.bat"
$IconIco = Join-Path $Root "website\public\luna-icon.ico"

if (-not (Test-Path $Bat)) {
  Write-Error "Missing: $Bat"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$Lnk = Join-Path $Desktop "Luna Website.lnk"

$Wsh = New-Object -ComObject WScript.Shell
$Sc = $Wsh.CreateShortcut($Lnk)
$Sc.TargetPath = $Bat
$Sc.WorkingDirectory = $Root
$Sc.WindowStyle = 1
$Sc.Description = "Open Luna marketing website (localhost:5180)"
if (Test-Path $IconIco) {
  $Sc.IconLocation = $IconIco
}
$Sc.Save()

Write-Host "Created: $Lnk"
Write-Host "You can pin that shortcut to the taskbar or Start menu."
