param(
    [Parameter(Mandatory=$true)][string]$BaselineInstallerPath,
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$CandidateManifestPath,
    [Parameter(Mandatory=$true)][string]$EvidenceDir
)

. "$PSScriptRoot\common.ps1"

function Get-ImageLabProjectEvidence {
    param(
        [Parameter(Mandatory=$true)][string]$BaseUrl,
        [Parameter(Mandatory=$true)][string]$DataRoot,
        [Parameter(Mandatory=$true)][string]$ProjectId,
        [Parameter(Mandatory=$true)][string]$ExpectedTitle,
        [Parameter(Mandatory=$true)][string]$ExpectedAssetSha256
    )

    $project = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/projects/$ProjectId" -TimeoutSec 30 -Headers @{ 'Cache-Control'='no-cache' }
    if ($project.id -ne $ProjectId) { throw "Project API returned wrong project ID" }
    if ($project.title -ne $ExpectedTitle) { throw "Project title changed" }
    $assets = @($project.assets)
    if ($assets.Count -ne 1) { throw "Project must contain exactly one preserved asset" }
    $asset = $assets[0]
    if ($asset.sha256 -ne $ExpectedAssetSha256) { throw "Project asset SHA differs from uploaded fixture" }
    if ($project.workspace.active_asset_id -ne $asset.id) { throw "Project active asset changed" }

    $projectPath = Join-Path $DataRoot "data\projects\$ProjectId.json"
    $assetPath = Join-Path $DataRoot ("data\uploads\" + $asset.stored_name)
    if (-not (Test-Path -LiteralPath $projectPath)) { throw "Project JSON missing: $projectPath" }
    if (-not (Test-Path -LiteralPath $assetPath)) { throw "Project asset file missing: $assetPath" }

    $assetFileSha = Get-Sha256 $assetPath
    if ($assetFileSha -ne $ExpectedAssetSha256 -or $assetFileSha -ne $asset.sha256) {
        throw "Persisted project asset bytes changed"
    }
    if ((Get-Item -LiteralPath $assetPath).Length -ne [int64]$asset.size_bytes) {
        throw "Persisted project asset size changed"
    }

    $diskProject = Get-Content -Raw -LiteralPath $projectPath | ConvertFrom-Json
    $diskAssets = @($diskProject.assets)
    if ($diskProject.id -ne $ProjectId -or $diskProject.title -ne $ExpectedTitle) {
        throw "Persisted project JSON identity changed"
    }
    if ($diskAssets.Count -ne 1 -or $diskAssets[0].id -ne $asset.id -or $diskAssets[0].sha256 -ne $asset.sha256 -or $diskAssets[0].stored_name -ne $asset.stored_name) {
        throw "Persisted project JSON asset record changed"
    }
    if ($diskProject.workspace.active_asset_id -ne $asset.id) {
        throw "Persisted project JSON active asset changed"
    }

    return [PSCustomObject][ordered]@{
        project_id = $ProjectId
        title = $ExpectedTitle
        asset_id = [string]$asset.id
        stored_name = [string]$asset.stored_name
        asset_record_sha256 = [string]$asset.sha256
        asset_file_sha256 = $assetFileSha
        asset_size_bytes = [int64]$asset.size_bytes
        project_file_sha256 = Get-Sha256 $projectPath
        active_asset_id = [string]$project.workspace.active_asset_id
    }
}

function Compare-ImageLabProjectEvidence {
    param(
        [Parameter(Mandatory=$true)][object]$Before,
        [Parameter(Mandatory=$true)][object]$After,
        [Parameter(Mandatory=$true)][string]$Phase
    )
    foreach ($field in @(
        'project_id', 'title', 'asset_id', 'stored_name', 'asset_record_sha256',
        'asset_file_sha256', 'asset_size_bytes', 'project_file_sha256', 'active_asset_id'
    )) {
        if ($Before.$field -ne $After.$field) {
            throw "$Phase project evidence mismatch: $field"
        }
    }
}

$BaselineInstallerPath = (Resolve-Path $BaselineInstallerPath).Path
$InstallerPath = (Resolve-Path $InstallerPath).Path
$CandidateManifestPath = (Resolve-Path $CandidateManifestPath).Path
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$candidate = Get-Content -Raw -LiteralPath $CandidateManifestPath | ConvertFrom-Json
$baselineInstallerSha = Get-Sha256 $BaselineInstallerPath
$installerSha = Get-Sha256 $InstallerPath
if ($installerSha -ne $candidate.installer.sha256) { throw "Candidate installer SHA mismatch" }
if ($baselineInstallerSha -eq $installerSha) { throw "Baseline and candidate installers must be different exact binaries" }

try {
    Stop-ImageLabProcesses
    $installDir = Get-ImageLabInstallDir
    $dataRoot = Join-Path $env:LOCALAPPDATA 'ImageLab by LarannA'
    if (Test-Path -LiteralPath $installDir) { Remove-Item -Recurse -Force -LiteralPath $installDir }
    if (Test-Path -LiteralPath $dataRoot) { Remove-Item -Recurse -Force -LiteralPath $dataRoot }

    $firstExit = Invoke-Installer -InstallerPath $BaselineInstallerPath -EvidenceDir $EvidenceDir -Prefix 'baseline-install'
    if ($firstExit -ne 0) { throw "Baseline install failed: $firstExit" }
    $first = Get-ImageLabManifest
    $firstHealth = Find-ImageLabHealth -Manifest $first -TimeoutSeconds 120

    # Keep a simple canary, but do not use it as the project-preservation proof.
    $sentinelDir = Join-Path $dataRoot 'projects'
    New-Item -ItemType Directory -Force -Path $sentinelDir | Out-Null
    $sentinel = Join-Path $sentinelDir 'zero-trust-update-sentinel.txt'
    "preserve-$($first.install_id)" | Set-Content -LiteralPath $sentinel -Encoding utf8

    # Create an actual project through the installed production API and upload
    # an exact SVG asset. Preserve both API metadata and on-disk bytes/hashes.
    $projectId = 'ZTR-UPDATE-PROJECT'
    $projectTitle = "Zero Trust Update $($first.install_id)"
    $createBody = @{ title = $projectTitle } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri "$($firstHealth.Url)/api/projects/$projectId" -ContentType 'application/json' -Body $createBody -TimeoutSec 30 | Out-Null

    $fixturePath = Join-Path $EvidenceDir 'update-project-fixture.svg'
    $fixtureSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48" viewBox="0 0 64 48"><rect width="64" height="48" fill="#f2f2f2"/><circle cx="24" cy="24" r="14" fill="#222222"/><rect x="38" y="10" width="16" height="28" fill="#e14b2a"/></svg>'
    [System.IO.File]::WriteAllText($fixturePath, $fixtureSvg, [System.Text.UTF8Encoding]::new($false))
    $fixtureSha = Get-Sha256 $fixturePath
    $upload = Invoke-RestMethod -Method Post -Uri "$($firstHealth.Url)/api/projects/$projectId/upload" -Form @{ files = Get-Item -LiteralPath $fixturePath } -TimeoutSec 60
    if (@($upload.uploaded).Count -ne 1) { throw "Project upload did not create exactly one asset" }

    $projectBefore = Get-ImageLabProjectEvidence -BaseUrl $firstHealth.Url -DataRoot $dataRoot -ProjectId $projectId -ExpectedTitle $projectTitle -ExpectedAssetSha256 $fixtureSha
    Write-Json $projectBefore (Join-Path $EvidenceDir 'project-before-update.json')

    # Keep the real previous version running and update it with the exact current candidate.
    $secondExit = Invoke-Installer -InstallerPath $InstallerPath -EvidenceDir $EvidenceDir -Prefix 'update-install'
    if ($secondExit -ne 0) { throw "Update install failed: $secondExit" }
    $second = Get-ImageLabManifest
    if ($second.install_id -eq $first.install_id) { throw "Update did not create a new install identity" }
    if ($second.version -ne $candidate.identity.version -or $second.build_id -ne $candidate.identity.build_id) { throw "Update did not install current candidate identity" }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw "Update deleted sentinel data" }
    $secondHealth = Find-ImageLabHealth -Manifest $second -TimeoutSeconds 120
    $projectAfterUpdate = Get-ImageLabProjectEvidence -BaseUrl $secondHealth.Url -DataRoot $dataRoot -ProjectId $projectId -ExpectedTitle $projectTitle -ExpectedAssetSha256 $fixtureSha
    Compare-ImageLabProjectEvidence -Before $projectBefore -After $projectAfterUpdate -Phase 'Update'
    Write-Json $projectAfterUpdate (Join-Path $EvidenceDir 'project-after-update.json')

    $oldStillRunning = $false
    foreach ($port in 8765..8799) {
        try {
            $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 1
            if ($probe.install_id -eq $first.install_id) { $oldStillRunning = $true }
        } catch { }
    }
    if ($oldStillRunning) { throw "Old ImageLab process survived update" }
    $criticalBefore = @{}
    foreach ($property in $second.critical_files.PSObject.Properties) { $criticalBefore[$property.Name] = $property.Value }
    Write-Json ([ordered]@{
        schema=2; status='PASS'; installer_sha256=$installerSha; baseline_installer_sha256=$baselineInstallerSha;
        baseline_version=$first.version; baseline_build_id=$first.build_id;
        first_install_id=$first.install_id; second_install_id=$second.install_id;
        first_url=$firstHealth.Url; second_url=$secondHealth.Url; old_process_stopped=$true;
        project_data_preserved=$true; sentinel_preserved=$true;
        project_evidence_before=$projectBefore; project_evidence_after_update=$projectAfterUpdate
    }) (Join-Path $EvidenceDir 'update-test.json')

    # Force a failure after atomic promotion. The exact pre-failure installation must return.
    $faultExit = Invoke-Installer -InstallerPath $InstallerPath -EvidenceDir $EvidenceDir -Prefix 'fault-install' -Fault 'after_promotion'
    if ($faultExit -eq 0) { throw "Fault-injected installer unexpectedly succeeded" }
    $restored = Get-ImageLabManifest
    if ($restored.install_id -ne $second.install_id) { throw "Rollback did not restore previous install identity" }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw "Rollback deleted sentinel data" }
    foreach ($property in $restored.critical_files.PSObject.Properties) {
        if (-not $criticalBefore.ContainsKey($property.Name) -or $criticalBefore[$property.Name] -ne $property.Value) { throw "Rollback critical hash mismatch: $($property.Name)" }
    }
    Stop-ImageLabProcesses
    $launcher = Join-Path $installDir 'ImageLab.exe'
    Start-Process -FilePath $launcher -WorkingDirectory $installDir | Out-Null
    $restoredHealth = Find-ImageLabHealth -Manifest $restored -TimeoutSeconds 120
    $projectAfterRollback = Get-ImageLabProjectEvidence -BaseUrl $restoredHealth.Url -DataRoot $dataRoot -ProjectId $projectId -ExpectedTitle $projectTitle -ExpectedAssetSha256 $fixtureSha
    Compare-ImageLabProjectEvidence -Before $projectAfterUpdate -After $projectAfterRollback -Phase 'Rollback'
    Write-Json $projectAfterRollback (Join-Path $EvidenceDir 'project-after-rollback.json')

    Write-Json ([ordered]@{
        schema=2; status='PASS'; installer_sha256=$installerSha;
        restored_install_id=$restored.install_id; expected_install_id=$second.install_id;
        fault_exit_code=$faultExit; restored_url=$restoredHealth.Url; critical_hashes_restored=$true;
        project_data_preserved=$true; sentinel_preserved=$true;
        project_evidence_before=$projectAfterUpdate; project_evidence_after_rollback=$projectAfterRollback
    }) (Join-Path $EvidenceDir 'rollback-test.json')
} catch {
    if (-not (Test-Path (Join-Path $EvidenceDir 'update-test.json'))) {
        Write-Json ([ordered]@{schema=2;status='FAIL';installer_sha256=$installerSha;error=$_.Exception.Message}) (Join-Path $EvidenceDir 'update-test.json')
    }
    if (-not (Test-Path (Join-Path $EvidenceDir 'rollback-test.json'))) {
        Write-Json ([ordered]@{schema=2;status='FAIL';installer_sha256=$installerSha;error=$_.Exception.Message}) (Join-Path $EvidenceDir 'rollback-test.json')
    }
    throw
}
