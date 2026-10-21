# Builds dist\InspectorsNotebook (the app folder) and dist\InspectorsNotebook-<version>-setup.exe.
#
#     powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Needs uv and Inno Setup 6 (winget install JRSoftware.InnoSetup).

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"$').Matches[0].Groups[1].Value

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }

uv run python packaging\make_icon.py build\inspectors-notebook.ico
if ($LASTEXITCODE) { throw "Drawing the icon failed" }

uv run pyinstaller packaging\inspectors-notebook.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE) { throw "PyInstaller failed" }

& $iscc /Q "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

Write-Output "Built dist\InspectorsNotebook-$version-setup.exe"
