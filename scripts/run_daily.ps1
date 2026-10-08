$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& python 'src/main.py' sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& python 'src/main.py' remind --send
exit $LASTEXITCODE
