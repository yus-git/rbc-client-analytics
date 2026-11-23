param(
    [Parameter(Mandatory)][string]$WorkspaceId,
    [Parameter(Mandatory)][string]$ReportId,
    [Parameter(Mandatory)][ValidateSet('Interactive', 'Paginated')][string]$ReportType,
    [Parameter(Mandatory)][ValidateSet('PDF', 'PNG', 'PPTX', 'XLSX', 'CSV')][string]$Format,
    [Parameter(Mandatory)][string]$OutputBase,
    [string]$PageName,
    [hashtable]$ReportParameters = @{ Month = '2026-10'; Region = 'All'; Scenario = 'Plan' }
)
$ErrorActionPreference = 'Stop'
if ($ReportType -eq 'Interactive' -and $Format -in @('XLSX', 'CSV')) {
    throw 'Interactive Excel/CSV is visual-data export in the UI, not whole-report ExportTo. Use the paginated report for full detail.'
}
if ($ReportType -eq 'Paginated' -and $Format -eq 'PNG') {
    throw 'Use PDF, XLSX or CSV for the paginated pack.'
}
if (Test-Path -LiteralPath "$OutputBase.request.json") {
    throw "A prior export is recorded at $OutputBase.request.json. Inspect its status; do not duplicate a pending export."
}
$parent = Split-Path -Parent $OutputBase
if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
$body = @{ format = $Format }
if ($ReportType -eq 'Interactive' -and $PageName) {
    $body.powerBIReportConfiguration = @{ pages = @(@{ pageName = $PageName }) }
} elseif ($ReportType -eq 'Paginated') {
    $body.paginatedReportConfiguration = @{ parameterValues = @(
        $ReportParameters.GetEnumerator() | ForEach-Object { @{ name = $_.Key; value = [string]$_.Value } }
    ) }
}
$token = az account get-access-token --resource 'https://analysis.windows.net/powerbi/api' --query accessToken -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Power BI authentication failed.' }
$headers = @{ Authorization = "Bearer $($token.Trim())" }
$base = "https://api.powerbi.com/v1.0/myorg/groups/$WorkspaceId/reports/$ReportId"
$export = Invoke-RestMethod -Method Post -Uri "$base/ExportTo" -Headers $headers `
    -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 10)
if (-not $export.id) { throw 'Export returned no job ID. Inspect the response before trying again.' }
@{ exportId = $export.id; reportId = $ReportId; request = $body } |
    ConvertTo-Json -Depth 10 | Set-Content -LiteralPath "$OutputBase.request.json" -Encoding utf8
for ($i = 0; $i -lt 100; $i++) {
    $state = Invoke-RestMethod -Uri "$base/exports/$($export.id)" -Headers $headers
    if ($state.status -in @('Succeeded', 'Failed')) { break }
    Start-Sleep -Seconds 3
}
$state | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath "$OutputBase.result.json" -Encoding utf8
if ($state.status -ne 'Succeeded') {
    $state | ConvertTo-Json -Depth 20 | Write-Output
    throw "Export $($export.id) is $($state.status); do not claim a rendered report."
}
if ($state.resourceFileExtension -notmatch '^\.(pdf|png|pptx|xlsx|csv|zip)$') {
    throw "Unexpected export extension: $($state.resourceFileExtension)"
}
$path = "$OutputBase$($state.resourceFileExtension)"
Invoke-WebRequest -Uri "$base/exports/$($export.id)/file" -Headers $headers -OutFile $path
if ((Get-Item -LiteralPath $path).Length -eq 0) { throw 'Downloaded export was empty.' }
Get-Item -LiteralPath $path | Select-Object FullName, Length
