param(
    [Parameter(Mandatory=$true)][string]$BaselineInstallerPath,
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$CandidateManifestPath,
    [Parameter(Mandatory=$true)][string]$EvidenceDir
)

. "$PSScriptRoot\common.ps1"

$script:CurrentStage = 'initialize'

function Invoke-ImageLabRest {
    param(
        [Parameter(Mandatory=$true)][string]$Stage,
        [Parameter(Mandatory=$true)][string]$Method,
        [Parameter(Mandatory=$true)][string]$Uri,
        [string]$ContentType,
        [object]$Body,
        [hashtable]$Form,
        [hashtable]$Headers,
        [int]$TimeoutSec = 30
    )
    $script:CurrentStage = $Stage
    $arguments = @{ Method=$Method; Uri=$Uri; TimeoutSec=$TimeoutSec }
    if ($ContentType) { $arguments.ContentType = $ContentType }
    if ($null -ne $Body) { $arguments.Body = $Body }
    if ($null -ne $Form) { $arguments.Form = $Form }
    if ($null -ne $Headers) { $arguments.Headers = $Headers }
    try {
        return Invoke-RestMethod @arguments
    } catch {
        $detail = [string]$_.ErrorDetails.Message
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = [string]$_.Exception.Message }
        throw "$Stage failed: $detail"
    }
}

function Get-BytesSha256 {
    param([Parameter(Mandatory=$true)][byte[]]$Bytes)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($algorithm.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function Get-ObjectSha256 {
    param([Parameter(Mandatory=$true)][object]$Value)
    $json = $Value | ConvertTo-Json -Depth 100 -Compress
    return Get-BytesSha256 ([System.Text.UTF8Encoding]::new($false).GetBytes($json))
}

function New-RasterFixture {
    param([Parameter(Mandatory=$true)][string]$Path)
    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new(96, 64)
    $bitmap.SetResolution(300, 300)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.Clear([System.Drawing.Color]::FromArgb(242, 242, 242))
        $graphics.FillRectangle([System.Drawing.Brushes]::Black, 10, 8, 46, 46)
        $graphics.FillEllipse([System.Drawing.Brushes]::OrangeRed, 50, 18, 34, 34)
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-ImageLabProjectInventory {
    param(
        [Parameter(Mandatory=$true)][string]$BaseUrl,
        [Parameter(Mandatory=$true)][string]$DataRoot,
        [Parameter(Mandatory=$true)][string]$ProjectId
    )

    $project = Invoke-ImageLabRest -Stage "inventory-project-$ProjectId" -Method Get -Uri "$BaseUrl/api/projects/$ProjectId" -TimeoutSec 30 -Headers @{ 'Cache-Control'='no-cache' }
    if ($project.id -ne $ProjectId) { throw "Project API returned wrong project ID: $ProjectId" }

    $projectPath = Join-Path $DataRoot "data\projects\$ProjectId.json"
    if (-not (Test-Path -LiteralPath $projectPath)) { throw "Project JSON missing: $projectPath" }
    $diskProject = Get-Content -Raw -LiteralPath $projectPath | ConvertFrom-Json
    if ($diskProject.id -ne $project.id -or $diskProject.title -ne $project.title) {
        throw "Project API/disk identity mismatch: $ProjectId"
    }

    $apiAssets = @($project.assets | Sort-Object id)
    $diskAssets = @($diskProject.assets | Sort-Object id)
    if ($apiAssets.Count -ne $diskAssets.Count) { throw "Project API/disk asset count mismatch: $ProjectId" }

    $assetInventory = @()
    foreach ($asset in $apiAssets) {
        $diskAsset = @($diskAssets | Where-Object { $_.id -eq $asset.id })
        if ($diskAsset.Count -ne 1) { throw "Project disk asset record missing or duplicated: $($asset.id)" }
        if ($diskAsset[0].stored_name -ne $asset.stored_name -or $diskAsset[0].sha256 -ne $asset.sha256) {
            throw "Project API/disk asset record mismatch: $($asset.id)"
        }

        $uploadPath = Join-Path $DataRoot ("data\uploads\" + $asset.stored_name)
        if (-not (Test-Path -LiteralPath $uploadPath)) { throw "Stored asset missing: $uploadPath" }
        $uploadSha = Get-Sha256 $uploadPath
        if ($uploadSha -ne [string]$asset.sha256) { throw "Stored asset SHA mismatch: $($asset.id)" }
        if ((Get-Item -LiteralPath $uploadPath).Length -ne [int64]$asset.size_bytes) {
            throw "Stored asset size mismatch: $($asset.id)"
        }

        $previewPath = Join-Path $DataRoot ("data\previews\" + $asset.preview_name)
        $previewSha = $null
        $previewSize = $null
        if (Test-Path -LiteralPath $previewPath) {
            $previewSha = Get-Sha256 $previewPath
            $previewSize = [int64](Get-Item -LiteralPath $previewPath).Length
        } elseif ($asset.format -ne 'SVG') {
            throw "Raster preview missing: $previewPath"
        }

        $assetInventory += [PSCustomObject][ordered]@{
            id = [string]$asset.id
            original_name = [string]$asset.original_name
            stored_name = [string]$asset.stored_name
            preview_name = [string]$asset.preview_name
            format = [string]$asset.format
            record_sha256 = [string]$asset.sha256
            upload_file_sha256 = $uploadSha
            upload_size_bytes = [int64]$asset.size_bytes
            preview_file_sha256 = $previewSha
            preview_size_bytes = $previewSize
            source_asset_id = if ($null -eq $asset.source_asset_id) { $null } else { [string]$asset.source_asset_id }
            operation = if ($null -eq $asset.operation) { $null } else { [string]$asset.operation }
            parameters_sha256 = Get-ObjectSha256 $asset.parameters
            ai_sha256 = Get-ObjectSha256 $asset.ai
        }
    }

    $workspace = $project.workspace
    $activeAssetId = if ($null -eq $workspace.active_asset_id) { $null } else { [string]$workspace.active_asset_id }
    if ($activeAssetId -and -not ($apiAssets.id -contains $activeAssetId)) {
        throw "Project active asset is absent: $ProjectId"
    }

    return [PSCustomObject][ordered]@{
        project_id = [string]$project.id
        title = [string]$project.title
        project_file_sha256 = Get-Sha256 $projectPath
        workspace_sha256 = Get-ObjectSha256 $workspace
        presets_sha256 = Get-ObjectSha256 $(if ($null -eq $workspace.presets) { @{} } else { $workspace.presets })
        active_asset_id = $activeAssetId
        active_revision = [int64]$(if ($null -eq $workspace.active_revision) { 0 } else { $workspace.active_revision })
        asset_count = [int]$apiAssets.Count
        assets = $assetInventory
    }
}

function Get-ImageLabDataInventory {
    param(
        [Parameter(Mandatory=$true)][string]$BaseUrl,
        [Parameter(Mandatory=$true)][string]$DataRoot
    )

    $listed = @((Invoke-ImageLabRest -Stage 'inventory-project-list' -Method Get -Uri "$BaseUrl/api/projects" -TimeoutSec 30 -Headers @{ 'Cache-Control'='no-cache' }) | Write-Output)
    $projects = @()
    foreach ($item in @($listed | Sort-Object id)) {
        $projects += Get-ImageLabProjectInventory -BaseUrl $BaseUrl -DataRoot $DataRoot -ProjectId ([string]$item.id)
    }
    $assetCount = 0
    foreach ($project in $projects) { $assetCount += [int]$project.asset_count }
    $projectsSha = Get-ObjectSha256 $projects
    return [PSCustomObject][ordered]@{
        schema = 1
        project_count = [int]$projects.Count
        asset_count = [int]$assetCount
        projects_sha256 = $projectsSha
        projects = $projects
    }
}

function Compare-ImageLabDataInventory {
    param(
        [Parameter(Mandatory=$true)][object]$Before,
        [Parameter(Mandatory=$true)][object]$After,
        [Parameter(Mandatory=$true)][string]$Phase
    )
    foreach ($field in @('schema', 'project_count', 'asset_count', 'projects_sha256')) {
        if ($Before.$field -ne $After.$field) { throw "$Phase data inventory mismatch: $field" }
    }
    if ((Get-ObjectSha256 $Before.projects) -ne (Get-ObjectSha256 $After.projects)) {
        throw "$Phase project inventory content mismatch"
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
    $script:CurrentStage = 'baseline-install'
    Stop-ImageLabProcesses
    $installDir = Get-ImageLabInstallDir
    $dataRoot = Join-Path $env:LOCALAPPDATA 'ImageLab by LarannA'
    if (Test-Path -LiteralPath $installDir) { Remove-Item -Recurse -Force -LiteralPath $installDir }
    if (Test-Path -LiteralPath $dataRoot) { Remove-Item -Recurse -Force -LiteralPath $dataRoot }

    $firstExit = Invoke-Installer -InstallerPath $BaselineInstallerPath -EvidenceDir $EvidenceDir -Prefix 'baseline-install'
    if ($firstExit -ne 0) { throw "Baseline install failed: $firstExit" }
    $first = Get-ImageLabManifest
    $firstHealth = Find-ImageLabHealth -Manifest $first -TimeoutSeconds 120

    $sentinelDir = Join-Path $dataRoot 'projects'
    New-Item -ItemType Directory -Force -Path $sentinelDir | Out-Null
    $sentinel = Join-Path $sentinelDir 'zero-trust-update-sentinel.txt'
    "preserve-$($first.install_id)" | Set-Content -LiteralPath $sentinel -Encoding utf8

    $svgProjectId = 'ZTR-SVG-PROJECT'
    $svgTitle = "SVG preservation $($first.install_id)"
    $rasterProjectId = 'ZTR-RASTER-PROJECT'
    $rasterTitle = "Raster history $($first.install_id)"

    foreach ($projectSpec in @(
        @{ id=$svgProjectId; title=$svgTitle },
        @{ id=$rasterProjectId; title=$rasterTitle }
    )) {
        $createBody = @{ title = $projectSpec.title } | ConvertTo-Json -Compress
        Invoke-ImageLabRest -Stage "create-project-$($projectSpec.id)" -Method Post -Uri "$($firstHealth.Url)/api/projects/$($projectSpec.id)" -ContentType 'application/json' -Body $createBody -TimeoutSec 30 | Out-Null
    }

    $svgPreset = @{ name='SVG-CLEAN'; module='cleanup'; parameters=@{ remove_halo=$true; remove_background=$false } } | ConvertTo-Json -Depth 10 -Compress
    Invoke-ImageLabRest -Stage 'set-svg-preset' -Method Put -Uri "$($firstHealth.Url)/api/projects/$svgProjectId/presets" -ContentType 'application/json' -Body $svgPreset -TimeoutSec 30 | Out-Null
    $rasterPreset = @{ name='PRINT-RESIZE'; module='geometry'; parameters=@{ width_mm=50.8; ppi=200; preserve_aspect=$true } } | ConvertTo-Json -Depth 10 -Compress
    Invoke-ImageLabRest -Stage 'set-raster-preset' -Method Put -Uri "$($firstHealth.Url)/api/projects/$rasterProjectId/presets" -ContentType 'application/json' -Body $rasterPreset -TimeoutSec 30 | Out-Null

    $svgFixturePath = Join-Path $EvidenceDir 'update-project-fixture.svg'
    $fixtureSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48" viewBox="0 0 64 48"><rect width="64" height="48" fill="#f2f2f2"/><circle cx="24" cy="24" r="14" fill="#222222"/><rect x="38" y="10" width="16" height="28" fill="#e14b2a"/></svg>'
    [System.IO.File]::WriteAllText($svgFixturePath, $fixtureSvg, [System.Text.UTF8Encoding]::new($false))
    $svgUpload = Invoke-ImageLabRest -Stage 'upload-svg' -Method Post -Uri "$($firstHealth.Url)/api/projects/$svgProjectId/upload" -Form @{ files = Get-Item -LiteralPath $svgFixturePath } -TimeoutSec 60
    $svgAssets = @($svgUpload.uploaded)
    if ($svgAssets.Count -ne 1) { throw "SVG project upload did not create exactly one asset" }
    Invoke-ImageLabRest -Stage 'activate-svg' -Method Post -Uri "$($firstHealth.Url)/api/projects/$svgProjectId/active" -ContentType 'application/json' -Body (@{asset_id=$svgAssets[0].id} | ConvertTo-Json -Compress) -TimeoutSec 30 | Out-Null

    $pngFixturePath = Join-Path $EvidenceDir 'update-raster-fixture.png'
    New-RasterFixture -Path $pngFixturePath
    $rasterUpload = Invoke-ImageLabRest -Stage 'upload-raster' -Method Post -Uri "$($firstHealth.Url)/api/projects/$rasterProjectId/upload" -Form @{ files = Get-Item -LiteralPath $pngFixturePath } -TimeoutSec 60
    $rasterAssets = @($rasterUpload.uploaded)
    if ($rasterAssets.Count -ne 1) { throw "Raster project upload did not create exactly one source asset" }
    $processBody = @{
        asset_id = [string]$rasterAssets[0].id
        operation = 'geometry'
        parameters = @{
            width_mm = 50.8; ppi = 200; preserve_aspect = $true;
            ai_auto_crop = $false; learn_from_result = $false
        }
    } | ConvertTo-Json -Depth 10 -Compress
    $processed = Invoke-ImageLabRest -Stage 'process-raster-geometry' -Method Post -Uri "$($firstHealth.Url)/api/projects/$rasterProjectId/process" -ContentType 'application/json' -Body $processBody -TimeoutSec 120
    if (-not $processed.result.id -or $processed.result.source_asset_id -ne $rasterAssets[0].id) {
        throw "Raster derived history was not created with valid lineage"
    }
    Invoke-ImageLabRest -Stage 'activate-raster-result' -Method Post -Uri "$($firstHealth.Url)/api/projects/$rasterProjectId/active" -ContentType 'application/json' -Body (@{asset_id=$processed.result.id} | ConvertTo-Json -Compress) -TimeoutSec 30 | Out-Null

    $inventoryBefore = Get-ImageLabDataInventory -BaseUrl $firstHealth.Url -DataRoot $dataRoot
    if ($inventoryBefore.project_count -lt 3) { throw "Expected default plus two preservation projects" }
    if ($inventoryBefore.asset_count -lt 3) { throw "Expected SVG source, raster source and derived raster asset" }
    Write-Json $inventoryBefore (Join-Path $EvidenceDir 'inventory-before-update.json')

    $script:CurrentStage = 'candidate-update-install'
    $secondExit = Invoke-Installer -InstallerPath $InstallerPath -EvidenceDir $EvidenceDir -Prefix 'update-install'
    if ($secondExit -ne 0) { throw "Update install failed: $secondExit" }
    $second = Get-ImageLabManifest
    if ($second.install_id -eq $first.install_id) { throw "Update did not create a new install identity" }
    if ($second.version -ne $candidate.identity.version -or $second.build_id -ne $candidate.identity.build_id) { throw "Update did not install current candidate identity" }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw "Update deleted sentinel data" }
    $secondHealth = Find-ImageLabHealth -Manifest $second -TimeoutSeconds 120
    $inventoryAfterUpdate = Get-ImageLabDataInventory -BaseUrl $secondHealth.Url -DataRoot $dataRoot
    Compare-ImageLabDataInventory -Before $inventoryBefore -After $inventoryAfterUpdate -Phase 'Update'
    Write-Json $inventoryAfterUpdate (Join-Path $EvidenceDir 'inventory-after-update.json')

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
        schema=3; status='PASS'; installer_sha256=$installerSha; baseline_installer_sha256=$baselineInstallerSha;
        baseline_version=$first.version; baseline_build_id=$first.build_id;
        first_install_id=$first.install_id; second_install_id=$second.install_id;
        first_url=$firstHealth.Url; second_url=$secondHealth.Url; old_process_stopped=$true;
        project_data_preserved=$true; sentinel_preserved=$true;
        project_count=$inventoryBefore.project_count; asset_count=$inventoryBefore.asset_count;
        project_inventory_before=$inventoryBefore; project_inventory_after_update=$inventoryAfterUpdate
    }) (Join-Path $EvidenceDir 'update-test.json')

    $script:CurrentStage = 'forced-failure-rollback'
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
    $inventoryAfterRollback = Get-ImageLabDataInventory -BaseUrl $restoredHealth.Url -DataRoot $dataRoot
    Compare-ImageLabDataInventory -Before $inventoryAfterUpdate -After $inventoryAfterRollback -Phase 'Rollback'
    Compare-ImageLabDataInventory -Before $inventoryBefore -After $inventoryAfterRollback -Phase 'End-to-end rollback'
    Write-Json $inventoryAfterRollback (Join-Path $EvidenceDir 'inventory-after-rollback.json')

    Write-Json ([ordered]@{
        schema=3; status='PASS'; installer_sha256=$installerSha;
        restored_install_id=$restored.install_id; expected_install_id=$second.install_id;
        fault_exit_code=$faultExit; restored_url=$restoredHealth.Url; critical_hashes_restored=$true;
        project_data_preserved=$true; sentinel_preserved=$true;
        project_count=$inventoryBefore.project_count; asset_count=$inventoryBefore.asset_count;
        project_inventory_before=$inventoryAfterUpdate; project_inventory_after_rollback=$inventoryAfterRollback
    }) (Join-Path $EvidenceDir 'rollback-test.json')
} catch {
    $failure = [ordered]@{
        schema=3; status='FAIL'; installer_sha256=$installerSha;
        stage=$script:CurrentStage; error=$_.Exception.Message
    }
    if (-not (Test-Path (Join-Path $EvidenceDir 'update-test.json'))) {
        Write-Json $failure (Join-Path $EvidenceDir 'update-test.json')
    }
    if (-not (Test-Path (Join-Path $EvidenceDir 'rollback-test.json'))) {
        Write-Json $failure (Join-Path $EvidenceDir 'rollback-test.json')
    }
    throw
}
