[CmdletBinding()]
param(
    [string]$OldProject = 'D:\opticalplatformcontrol\microscope-control'
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$driverDir = Join-Path $projectRoot 'drivers\aseq'
$oldDriverDir = Join-Path $OldProject 'drivers\aseq'

Write-Host "Project: $projectRoot"
Write-Host 'Expected work-computer Python: 3.11.9, 64-bit'

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.11 -m venv (Join-Path $projectRoot '.venv')
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $venvPython -m pip install -e $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }

New-Item -ItemType Directory -Path $driverDir -Force | Out-Null
foreach ($name in @('spectrlib_shared_64bits.dll', 'aseq_wavelengths_latest.txt')) {
    $destination = Join-Path $driverDir $name
    $source = Join-Path $oldDriverDir $name
    if (-not (Test-Path -LiteralPath $destination) -and (Test-Path -LiteralPath $source)) {
        Copy-Item -LiteralPath $source -Destination $destination
        Write-Host "Copied from old project: $name"
    }
}

Write-Host ''
Write-Host 'Setup finished. Next run:'
Write-Host '  .\run.ps1 doctor'
Write-Host 'If Arduino is not COM3, edit config\work_computer.toml.'

