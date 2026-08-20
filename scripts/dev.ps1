$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv. Run the setup commands in README.md first.'
}
Set-Location $projectRoot
& $pythonPath -m uvicorn news_claws.main:app --app-dir apps/analysis_api --host 127.0.0.1 --port 8000 --reload
