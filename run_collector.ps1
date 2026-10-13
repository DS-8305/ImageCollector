param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CollectorArgs)
$ErrorActionPreference = 'Stop'
$collectorPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $collectorPython)) {
    throw '먼저 README의 Python 가상 환경 설치를 진행하세요.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $collectorPython (Join-Path $PSScriptRoot 'naver_image_collector.py') @CollectorArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
