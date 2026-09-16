$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { Write-Host "Install Windows Python 3.12+ (with py.exe) first." -ForegroundColor Red; exit 1 }
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $PSScriptRoot ".venv\Scripts\pyinstaller.exe"
& $python -m pip install --upgrade pip pyinstaller
& $pyinstaller --noconsole --onefile --clean --name "PalisadeDB" "palisadedb_desktop.pyw"
Write-Host "Built: $PSScriptRoot\dist\PalisadeDB.exe" -ForegroundColor Green
