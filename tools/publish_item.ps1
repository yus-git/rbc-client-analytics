#requires -Version 7.0
param(
    [Parameter(Mandatory)][ValidateSet('semanticModels','reports','paginatedReports')][string]$Collection,
    [Parameter(Mandatory)][guid]$WorkspaceId,
    [Parameter(Mandatory)][string]$RequestPath,
    [Parameter(Mandatory)][string]$ResultPath,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
if (-not $request.displayName -or -not $request.definition.parts) { throw 'Missing item name or definition.' }
if (-not $Apply) {
    Write-Output "PLAN ONLY: create $Collection '$($request.displayName)' in $WorkspaceId. Use -Apply after review."
    return
}
if (Test-Path -LiteralPath $ResultPath) { throw 'A result already exists; inspect it instead of duplicating the item.' }
if (Test-Path -LiteralPath "$ResultPath.operation.json") { throw 'A prior operation exists; inspect it before resubmitting.' }
$token = az account get-access-token --resource 'https://api.fabric.microsoft.com' --query accessToken -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Azure CLI authentication failed.' }
$headers = @{ Authorization = "Bearer $($token.Trim())" }
$base = 'https://api.fabric.microsoft.com/v1'
$workspace = Invoke-RestMethod "$base/workspaces/$WorkspaceId" -Headers $headers -TimeoutSec 60
if (-not $workspace.capacityId) { throw 'Assign this workspace to active Fabric capacity before publishing.' }
$capacity = Invoke-RestMethod "$base/capacities/$($workspace.capacityId)" -Headers $headers -TimeoutSec 60
if ($capacity.state -ne 'Active') { throw "Capacity is not Active: $($capacity.state)" }
$url = "$base/workspaces/$WorkspaceId/$Collection"
$next = $url
do {
    $page = Invoke-RestMethod $next -Headers $headers -TimeoutSec 60
    if ($page.value | Where-Object displayName -eq $request.displayName) {
        throw 'An item with this name already exists. This first-deployment helper never overwrites it.'
    }
    $next = $page.continuationUri
} while ($next)
$parent = Split-Path -Parent ([IO.Path]::GetFullPath($ResultPath))
New-Item -ItemType Directory -Force -Path $parent | Out-Null
# Persist the intent first: even a transport timeout must not trigger a blind create retry.
@{ status = 'Submitting'; collection = $Collection; name = $request.displayName; workspace = "$WorkspaceId" } |
    ConvertTo-Json | Set-Content -LiteralPath "$ResultPath.operation.json" -Encoding utf8
$response = Invoke-WebRequest -Method Post -Uri $url -Headers $headers -ContentType 'application/json' `
    -Body ([Text.Encoding]::UTF8.GetBytes(($request | ConvertTo-Json -Depth 60))) -TimeoutSec 120
if ([int]$response.StatusCode -eq 202) {
    $id = [string]@($response.Headers['x-ms-operation-id'])[0]
    if (-not $id) { throw 'Missing operation ID; inspect workspace and do not resubmit.' }
    @{ operationId = $id; collection = $Collection; workspace = "$WorkspaceId" } |
        ConvertTo-Json | Set-Content -LiteralPath "$ResultPath.operation.json" -Encoding utf8
    for ($i = 0; $i -lt 120; $i++) {
        $state = Invoke-RestMethod "$base/operations/$id" -Headers $headers -TimeoutSec 60
        if ($state.status -eq 'Succeeded') { break }
        if ($state.status -in @('Failed','Cancelled')) { throw ($state | ConvertTo-Json -Depth 20) }
        Start-Sleep -Seconds 5
    }
    if ($state.status -ne 'Succeeded') { throw "Operation $id is still $($state.status); monitor it, do not recreate." }
    $result = Invoke-RestMethod "$base/operations/$id/result" -Headers $headers -TimeoutSec 60
} else {
    $text = if ($response.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($response.Content) } else { [string]$response.Content }
    $result = $text | ConvertFrom-Json
}
if (-not $result.id) { throw 'No item ID returned; inspect the operation before continuing.' }
$verified = Invoke-RestMethod "$url/$($result.id)" -Headers $headers -TimeoutSec 60
$verified | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ResultPath -Encoding utf8
$verified | Select-Object id,displayName,type
