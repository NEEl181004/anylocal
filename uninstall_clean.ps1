# AnyLocal Clean Removal Script
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Cleaning AnyLocal Background & Startup " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Stop background process
Write-Host "[1/4] Stopping any running background instances..." -ForegroundColor Yellow
Get-Process -Name AnyLocal -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. Remove from Windows Startup Registry
Write-Host "[2/4] Removing auto-start from Windows Registry..." -ForegroundColor Yellow
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "AnyLocal" -ErrorAction SilentlyContinue

# 3. Remove Startup folder shortcut
Write-Host "[3/4] Removing Windows Startup folder shortcut..." -ForegroundColor Yellow
$startupLnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\AnyLocal.lnk"
if (Test-Path $startupLnk) {
    Remove-Item $startupLnk -Force
    Write-Host "      Removed: $startupLnk" -ForegroundColor Gray
}

# 4. Remove saved settings and PIN cache
Write-Host "[4/4] Removing saved config & PIN cache..." -ForegroundColor Yellow
$configPath = "$env:USERPROFILE\.anylocal_config.json"
if (Test-Path $configPath) {
    Remove-Item $configPath -Force
    Write-Host "      Removed: $configPath" -ForegroundColor Gray
}

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host " SUCCESS: AnyLocal completely removed! " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "To reinstall/start fresh:" -ForegroundColor White
Write-Host "Double-click 'AnyLocal.exe' on your Desktop or in dist\AnyLocal.exe." -ForegroundColor Cyan
