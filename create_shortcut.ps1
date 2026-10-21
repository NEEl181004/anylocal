$desktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$shortcutPath = Join-Path $desktopPath "AnyLocal.lnk"
$targetExe = "C:\Users\Admin\Desktop\Anyserver\dist\AnyLocal.exe"

$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetExe
$shortcut.WorkingDirectory = "C:\Users\Admin\Desktop\Anyserver\dist"
$shortcut.Description = "AnyLocal Remote Desktop"
$shortcut.Save()
Write-Host "Created shortcut at $shortcutPath"
