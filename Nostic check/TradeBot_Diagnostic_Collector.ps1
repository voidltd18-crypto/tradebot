param(
    [string]$BaseUrl = "https://tradebot-0myo.onrender.com",
    [string]$ApiKey = "",
    [string]$OutputRoot = "$env:USERPROFILE\Desktop"
)

$ErrorActionPreference = "Continue"

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    $ApiKey = Read-Host "Enter your TradeBot API key"
}

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$folderName = "TradeBot_Diagnostics_$timestamp"
$outputFolder = Join-Path $OutputRoot $folderName
$zipPath = "$outputFolder.zip"

New-Item -ItemType Directory -Path $outputFolder -Force | Out-Null

$headers = @{
    "x-api-key" = $ApiKey
}

$endpoints = [ordered]@{
    "status"                     = "/status"
    "banking-status"             = "/banking-status"
    "reports"                    = "/reports"
    "ai-position-capacity"       = "/ai-position-capacity"
    "adaptive-thresholds"        = "/adaptive-thresholds/status"

    "ai-advisor"                 = "/ai-advisor/summary"
    "strategy-intelligence"      = "/strategy-intelligence/summary"
    "symbol-intelligence"        = "/symbol-intelligence/summary"
    "rule-intelligence"          = "/rule-intelligence/summary"
    "decision-intelligence"      = "/decision-intelligence/summary"
    "weakness-intelligence"      = "/weakness-intelligence/summary"
    "shadow-trading"             = "/shadow-trading/summary"

    "v7-status"                  = "/v7/status"
    "v8-status"                  = "/v8/status"
    "v10-operator-status"        = "/v10/operator/status"

    "v12-ceo-status"             = "/v12/ceo/status?journal_limit=40"
    "v12-ceo-journal"            = "/v12/ceo/journal?limit=100"
    "v12-ceo-reviews"            = "/v12/ceo/reviews?limit=30"
    "v12-ceo-constitution"       = "/v12/ceo/constitution"

    "v12-board-status"           = "/v12/board/status"
    "v12-board-constitution"     = "/v12/board/constitution"

    "v13-memory-status"          = "/v13/memory/status"
    "v13-memory-events"          = "/v13/memory/events?limit=100"
    "v13-memory-knowledge"       = "/v13/memory/knowledge?limit=200"
    "v13-memory-constitution"    = "/v13/memory/constitution"

    "v14-scientist-status"       = "/v14/scientist/status"
    "v14-scientist-events"       = "/v14/scientist/events?limit=100"
    "v14-scientist-hypotheses"   = "/v14/scientist/hypotheses?limit=200"
    "v14-scientist-experiments"  = "/v14/scientist/experiments?limit=200"
    "v14-scientist-constitution" = "/v14/scientist/constitution"

    "v15-operations-status"       = "/v15/operations/status"
    "v15-operations-components"   = "/v15/operations/components"
    "v15-operations-alerts"       = "/v15/operations/alerts?limit=100&status=ACTIVE"
    "v15-operations-history"      = "/v15/operations/history?limit=100"
    "v15-operations-dependencies" = "/v15/operations/dependencies"
    "v15-operations-watchdogs"    = "/v15/operations/watchdogs"
    "v15-operations-queues"       = "/v15/operations/queues"
    "v15-operations-doctor"       = "/v15/operations/doctor"
    "v15-operations-health"       = "/v15/operations/engine-health"
    "v15-operations-constitution" = "/v15/operations/constitution"
}

$summary = New-Object System.Collections.Generic.List[object]

Write-Host ""
Write-Host "Collecting TradeBot diagnostics..." -ForegroundColor Cyan
Write-Host "Output folder: $outputFolder"
Write-Host ""

foreach ($name in $endpoints.Keys) {
    $path = $endpoints[$name]
    $uri = "$BaseUrl$path"
    $safeName = ($name -replace '[^a-zA-Z0-9._-]', '_')
    $jsonPath = Join-Path $outputFolder "$safeName.json"
    $errorPath = Join-Path $outputFolder "$safeName.error.txt"

    $started = Get-Date
    try {
        $response = Invoke-RestMethod `
            -Method Get `
            -Uri $uri `
            -Headers $headers `
            -TimeoutSec 90

        $response |
            ConvertTo-Json -Depth 100 |
            Set-Content -Path $jsonPath -Encoding UTF8

        $elapsed = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 0)

        $summary.Add([pscustomobject]@{
            Name       = $name
            Endpoint   = $path
            Status     = "OK"
            DurationMs = $elapsed
            File       = [System.IO.Path]::GetFileName($jsonPath)
            Error      = ""
        })

        Write-Host ("[OK]   {0,-32} {1,8} ms" -f $name, $elapsed) -ForegroundColor Green
    }
    catch {
        $elapsed = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 0)
        $message = $_.Exception.Message

        @"
Endpoint: $uri
Time: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
DurationMs: $elapsed
Error: $message

Full error:
$($_ | Out-String)
"@ | Set-Content -Path $errorPath -Encoding UTF8

        $summary.Add([pscustomobject]@{
            Name       = $name
            Endpoint   = $path
            Status     = "FAILED"
            DurationMs = $elapsed
            File       = [System.IO.Path]::GetFileName($errorPath)
            Error      = $message
        })

        Write-Host ("[FAIL] {0,-32} {1}" -f $name, $message) -ForegroundColor Red
    }
}

$summary |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path (Join-Path $outputFolder "diagnostic-summary.json") -Encoding UTF8

$summary |
    Export-Csv -Path (Join-Path $outputFolder "diagnostic-summary.csv") -NoTypeInformation -Encoding UTF8

$failed = @($summary | Where-Object { $_.Status -eq "FAILED" }).Count
$passed = @($summary | Where-Object { $_.Status -eq "OK" }).Count

@"
TradeBot Diagnostic Collection

Created: $(Get-Date -Format "dd/MM/yyyy HH:mm:ss")
Base URL: $BaseUrl
Endpoints checked: $($summary.Count)
Passed: $passed
Failed: $failed

Upload the ZIP file to ChatGPT for review:
$zipPath
"@ | Set-Content -Path (Join-Path $outputFolder "README.txt") -Encoding UTF8

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path "$outputFolder\*" -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Finished." -ForegroundColor Cyan
Write-Host "Passed: $passed" -ForegroundColor Green
Write-Host "Failed: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })
Write-Host ""
Write-Host "ZIP saved here:" -ForegroundColor Yellow
Write-Host $zipPath -ForegroundColor Yellow
Write-Host ""
Write-Host "Upload that ZIP file here."
