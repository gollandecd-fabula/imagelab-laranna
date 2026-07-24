param(
    [Parameter(Mandatory=$true)][string]$BaselineInstallerPath,
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$CandidateManifestPath,
    [Parameter(Mandatory=$true)][string]$EvidenceDir
)

. "$PSScriptRoot\common.ps1"
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
    $sentinelDir = Join-Path $dataRoot 'projects'
    New-Item -ItemType Directory -Force -Path $sentinelDir | Out-Null
    $sentinel = Join-Path $sentinelDir 'zero-trust-update-sentinel.txt'
    "preserve-$($first.install_id)" | Set-Content -LiteralPath $sentinel -Encoding utf8

    # Keep the real previous version running and update it with the exact current candidate.
    $secondExit = Invoke-Installer -InstallerPath $InstallerPath -EvidenceDir $EvidenceDir -Prefix 'update-install'
    if ($secondExit -ne 0) { throw "Update install failed: $secondExit" }
    $second = Get-ImageLabManifest
    if ($second.install_id -eq $first.install_id) { throw "Update did not create a new install identity" }
    if ($second.version -ne $candidate.identity.version -or $second.build_id -ne $candidate.identity.build_id) { throw "Update did not install current candidate identity" }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw "Update deleted existing project data" }
    $secondHealth = Find-ImageLabHealth -Manifest $second -TimeoutSeconds 120
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
        schema=1; status='PASS'; installer_sha256=$installerSha; baseline_installer_sha256=$baselineInstallerSha;
        baseline_version=$first.version; baseline_build_id=$first.build_id;
        first_install_id=$first.install_id; second_install_id=$second.install_id;
        first_url=$firstHealth.Url; second_url=$secondHealth.Url; old_process_stopped=$true; project_data_preserved=$true
    }) (Join-Path $EvidenceDir 'update-test.json')

    # Force a failure after atomic promotion. The exact pre-failure installation must return.
    $faultExit = Invoke-Installer -InstallerPath $InstallerPath -EvidenceDir $EvidenceDir -Prefix 'fault-install' -Fault 'after_promotion'
    if ($faultExit -eq 0) { throw "Fault-injected installer unexpectedly succeeded" }
    $restored = Get-ImageLabManifest
    if ($restored.install_id -ne $second.install_id) { throw "Rollback did not restore previous install identity" }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw "Rollback deleted existing project data" }
    foreach ($property in $restored.critical_files.PSObject.Properties) {
        if (-not $criticalBefore.ContainsKey($property.Name) -or $criticalBefore[$property.Name] -ne $property.Value) { throw "Rollback critical hash mismatch: $($property.Name)" }
    }
    Stop-ImageLabProcesses
    $launcher = Join-Path $installDir 'ImageLab.exe'
    Start-Process -FilePath $launcher -WorkingDirectory $installDir | Out-Null
    $restoredHealth = Find-ImageLabHealth -Manifest $restored -TimeoutSeconds 120
    Write-Json ([ordered]@{
        schema=1; status='PASS'; installer_sha256=$installerSha;
        restored_install_id=$restored.install_id; expected_install_id=$second.install_id;
        fault_exit_code=$faultExit; restored_url=$restoredHealth.Url; critical_hashes_restored=$true; project_data_preserved=$true
    }) (Join-Path $EvidenceDir 'rollback-test.json')
} catch {
    if (-not (Test-Path (Join-Path $EvidenceDir 'update-test.json'))) {
        Write-Json ([ordered]@{schema=1;status='FAIL';installer_sha256=$installerSha;error=$_.Exception.Message}) (Join-Path $EvidenceDir 'update-test.json')
    }
    if (-not (Test-Path (Join-Path $EvidenceDir 'rollback-test.json'))) {
        Write-Json ([ordered]@{schema=1;status='FAIL';installer_sha256=$installerSha;error=$_.Exception.Message}) (Join-Path $EvidenceDir 'rollback-test.json')
    }
    throw
}
