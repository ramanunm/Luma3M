$ErrorActionPreference = 'Stop'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    $oldVenvPython = 'D:\opticalplatformcontrol\microscope-control\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $oldVenvPython) {
        $venvPython = $oldVenvPython
        Write-Host "Using the existing old-project Python environment: $venvPython"
    }
    else {
        throw 'Python environment not found. Run .\setup_work_computer.ps1 first.'
    }
}

Push-Location $PSScriptRoot
try {
    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = if ($previousPythonPath) { "$PSScriptRoot;$previousPythonPath" } else { $PSScriptRoot }
    & $venvPython -m microscope_control @args
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
