$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$ShortcutPath = Join-Path $DesktopPath "Don Pollo POS.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $DesktopPath "DonPollo_POS_Portable\DonPolloPOS.exe"
$Shortcut.WorkingDirectory = Join-Path $DesktopPath "DonPollo_POS_Portable"
$Shortcut.Description = "Sistema Don Pollo POS - Punto de Venta e Inventario"
$Shortcut.Save()
Write-Host "Acceso directo creado en: $ShortcutPath"
