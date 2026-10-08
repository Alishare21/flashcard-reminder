$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_daily.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $runner) -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
Register-ScheduledTask -TaskName 'Flashcard Daily Reminder' -Action $action -Trigger $trigger -Description 'Sync local flashcards and send one due-card email at 8 AM.' -Force | Out-Null
Write-Output 'Flashcard Daily Reminder scheduled for 8:00 AM local time.'
