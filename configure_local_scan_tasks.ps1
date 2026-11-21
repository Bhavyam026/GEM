$ErrorActionPreference = "Stop"

# Enable catch-up after a missed start and wake from sleep/hibernate.
# Windows cannot execute a task while the computer is fully shut down.
$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$folder = $service.GetFolder("\")

$days = @("MON", "TUE", "WED", "THU", "FRI", "SAT")
$times = @("0900", "1100", "1300", "1500", "1700")
$updated = 0
$failed = 0

foreach ($day in $days) {
    foreach ($time in $times) {
        $name = "GeM Tender Auto Scan $day $time"
        try {
            $task = $folder.GetTask($name)
            $definition = $task.Definition
            $definition.Settings.StartWhenAvailable = $true
            $definition.Settings.WakeToRun = $true
            $definition.Settings.MultipleInstances = 2
            $userId = $definition.Principal.UserId
            $folder.RegisterTaskDefinition($name, $definition, 6, $userId, $null, 3, $null) | Out-Null
            Write-Host "Updated: $name"
            $updated++
        }
        catch {
            Write-Host "FAILED: $name - $($_.Exception.Message)"
            $failed++
        }
    }
}

Write-Host ""
Write-Host "Updated tasks: $updated"
Write-Host "Failed tasks: $failed"
if ($failed -gt 0) { exit 1 }
exit 0
