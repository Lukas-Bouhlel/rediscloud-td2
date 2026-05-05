param(
  [string]$ProjectId = "td-cloud-495410",
  [string]$Region = "europe-west1",
  [string]$Service1 = "instance-1",
  [string]$Service2 = "instance-2",
  [string]$Bucket = "game-snapshots-td-cloud-495410",
  [string]$AdminKey = "td-secret-2026",
  [switch]$OpenBrowsers
)

$ErrorActionPreference = "Stop"

function Get-ServiceUrl {
  param([string]$ServiceName)
  gcloud run services describe $ServiceName --project $ProjectId --region $Region --format "value(status.url)"
}

function Test-Health {
  param([string]$Url)
  try {
    $h = Invoke-RestMethod -Method Get -Uri "$Url/health"
    return ($h.status -eq "healthy")
  }
  catch {
    return $false
  }
}

function Get-StatusCodeFromException {
  param($ExceptionObject)
  try {
    return [int]$ExceptionObject.Response.StatusCode
  }
  catch {
    return -1
  }
}

$u1 = Get-ServiceUrl -ServiceName $Service1
$u2 = Get-ServiceUrl -ServiceName $Service2

Write-Host "Instance 1: $u1"
Write-Host "Instance 2: $u2"

if ($OpenBrowsers) {
  Start-Process $u1
  Start-Process $u2
  Write-Host "Onglets ouverts pour test visuel."
}

Write-Host ""
Write-Host "== 1) Health checks =="
$okH1 = Test-Health -Url $u1
$okH2 = Test-Health -Url $u2
Write-Host "Health ${Service1}: $okH1"
Write-Host "Health ${Service2}: $okH2"

Write-Host ""
Write-Host "== 2) Publish + snapshot (Cloud Tasks + GCS) =="
$payload = @{ message = "phase3-test-$(Get-Date -Format HHmmss)" } | ConvertTo-Json -Compress
$pub = Invoke-RestMethod -Method Post -Uri "$u1/publish" -ContentType "application/json" -Headers @{ "X-Player-ID" = "demo-player" } -Body $payload
Write-Host "Publish status: $($pub.status)"
Write-Host "Redis key: $($pub.redis_key)"
Start-Sleep -Seconds 5
$snaps = gcloud storage ls "gs://$Bucket/snapshots/**" 2>$null
$snapCount = ($snaps | Measure-Object).Count
$lastSnap = $null
if ($snapCount -gt 0) { $lastSnap = $snaps | Select-Object -Last 1 }
Write-Host "Snapshot count: $snapCount"
Write-Host "Last snapshot: $lastSnap"

Write-Host ""
Write-Host "== 3) Rate limit (attendu: 200 x5 puis 429) =="
$rateResults = @()
foreach ($i in 1..7) {
  $msg = @{ message = "rate-$i" } | ConvertTo-Json -Compress
  try {
    Invoke-RestMethod -Method Post -Uri "$u1/publish" -ContentType "application/json" -Headers @{ "X-Player-ID" = "rate-limit-42" } -Body $msg | Out-Null
    $rateResults += 200
  }
  catch {
    $rateResults += (Get-StatusCodeFromException -ExceptionObject $_.Exception)
  }
  Start-Sleep -Milliseconds 250
}
Write-Host "Rate results: $($rateResults -join ', ')"

Write-Host ""
Write-Host "== 4) Analytics auth =="
$unauthCode = 0
try {
  Invoke-RestMethod -Method Get -Uri "$u1/analytics" | Out-Null
  $unauthCode = 200
}
catch {
  $unauthCode = Get-StatusCodeFromException -ExceptionObject $_.Exception
}
$auth = Invoke-RestMethod -Method Get -Uri "$u1/analytics" -Headers @{ "X-Admin-Key" = $AdminKey }
$analyticsCount = ($auth.analytics.PSObject.Properties.Name | Measure-Object).Count
$quotaCount = ($auth.quotas.PSObject.Properties.Name | Measure-Object).Count
Write-Host "Analytics without key (expected 401): $unauthCode"
Write-Host "Analytics docs count: $analyticsCount"
Write-Host "Quota docs count: $quotaCount"

Write-Host ""
Write-Host "== 5) Resume =="
$ratePass = ($rateResults[0..4] -notcontains 429) -and ($rateResults[5] -eq 429) -and ($rateResults[6] -eq 429)
$allPass = $okH1 -and $okH2 -and ($pub.status -eq "published") -and ($snapCount -ge 1) -and $ratePass -and ($unauthCode -eq 401)
Write-Host "PASS Health: $($okH1 -and $okH2)"
Write-Host "PASS Snapshot: $($snapCount -ge 1)"
Write-Host "PASS RateLimit: $ratePass"
Write-Host "PASS AnalyticsAuth: $($unauthCode -eq 401)"
Write-Host "GLOBAL PASS: $allPass"
