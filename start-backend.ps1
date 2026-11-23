$ErrorActionPreference = 'Stop'
$journalBackend = Join-Path $PSScriptRoot 'backend'
$journalPython = Join-Path $journalBackend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $journalPython)) {
    throw 'Create backend/.venv and install backend/requirements.txt first. See docs/quickstart.md.'
}
Set-Location -LiteralPath $journalBackend
& $journalPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
