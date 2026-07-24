param(
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$CandidateManifestPath,
    [Parameter(Mandatory=$true)][string]$EvidenceDir,
    [ValidateSet('clean','independent')][string]$Mode = 'clean',
    [ValidateSet('bundled','msedge')][string]$BrowserChannel = 'bundled'
)

. "$PSScriptRoot\common.ps1"
$InstallerPath = (Resolve-Path $InstallerPath).Path
$CandidateManifestPath = (Resolve-Path $CandidateManifestPath).Path
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$candidate = Get-Content -Raw -LiteralPath $CandidateManifestPath | ConvertFrom-Json
$installerSha = Get-Sha256 $InstallerPath
if ($installerSha -ne $candidate.installer.sha256) { throw "Candidate installer SHA mismatch" }

# Materialize a private copy of the external release-gate interpreter before
# the installer starts. Installing ImageLab's private Python can invalidate the
# GitHub toolcache interpreter path even though that path worked moments earlier.
# The full runtime copy keeps Python, its stdlib, DLLs and already-installed
# Playwright/Pillow packages outside both toolcache and the ImageLab install tree.
$sourceGatePython = (& python -c "import sys; print(sys.executable)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceGatePython -or -not (Test-Path -LiteralPath $sourceGatePython)) {
    throw "Release gate source Python executable not found"
}
$sourceGateRoot = Split-Path -Parent $sourceGatePython
$gateTempBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
$gateRuntimeRoot = Join-Path $gateTempBase ("imagelab-release-gate-python-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateRuntimeRoot | Out-Null
& robocopy.exe $sourceGateRoot $gateRuntimeRoot /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
$robocopyExitCode = $LASTEXITCODE
$global:LASTEXITCODE = 0
if ($robocopyExitCode -gt 7) {
    throw "Release gate Python runtime copy failed with robocopy code $robocopyExitCode"
}
$gatePython = Join-Path $gateRuntimeRoot 'python.exe'
if (-not (Test-Path -LiteralPath $gatePython)) {
    throw "Copied release gate Python executable not found"
}
$gatePythonSha = Get-Sha256 $gatePython
& $gatePython -c "import sys, PIL; import playwright.sync_api; print(sys.executable)"
if ($LASTEXITCODE -ne 0) { throw "Copied release gate Python dependencies are unavailable" }

$verdictName = if ($Mode -eq 'independent') { 'independent-verification.json' } else { 'clean-install.json' }
try {
    Stop-ImageLabProcesses
    $installDir = Get-ImageLabInstallDir
    if (Test-Path -LiteralPath $installDir) { Remove-Item -Recurse -Force -LiteralPath $installDir }
    $dataRoot = Join-Path $env:LOCALAPPDATA 'ImageLab by LarannA'
    if (Test-Path -LiteralPath $dataRoot) { Remove-Item -Recurse -Force -LiteralPath $dataRoot }

    $exitCode = Invoke-Installer -InstallerPath $InstallerPath -EvidenceDir $EvidenceDir -Prefix 'installer'
    if ($exitCode -ne 0) { throw "Installer exited with code $exitCode" }
    $manifest = Get-ImageLabManifest
    if ($manifest.version -ne $candidate.identity.version -or $manifest.build_id -ne $candidate.identity.build_id) { throw "Installed identity differs from candidate" }
    $health = Find-ImageLabHealth -Manifest $manifest -TimeoutSeconds 120

    $preSelfTest = Join-Path (Get-ImageLabInstallDir) 'release-evidence\preinstall-selftest.json'
    $postSelfTest = Join-Path $env:LOCALAPPDATA 'ImageLab by LarannA\release-evidence\postinstall-selftest.json'
    if (-not (Test-Path $preSelfTest)) { throw "Preinstall self-test evidence missing" }
    if (-not (Test-Path $postSelfTest)) { throw "Postinstall self-test evidence missing" }
    Copy-Item $preSelfTest (Join-Path $EvidenceDir 'preinstall-selftest.json') -Force
    Copy-Item $postSelfTest (Join-Path $EvidenceDir 'postinstall-selftest.json') -Force
    $pre = Get-Content -Raw $preSelfTest | ConvertFrom-Json
    $post = Get-Content -Raw $postSelfTest | ConvertFrom-Json
    if ($pre.status -ne 'PASS' -or $post.status -ne 'PASS') { throw "Embedded self-test did not pass" }

    if (-not (Test-Path -LiteralPath $gatePython)) {
        throw "Copied release gate Python disappeared after installation"
    }
    if ((Get-Sha256 $gatePython) -ne $gatePythonSha) {
        throw "Copied release gate Python changed during installation"
    }
    & $gatePython -c "import sys, PIL; import playwright.sync_api; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) { throw "Copied release gate Python failed after installation" }

    $envInfo = [ordered]@{
        schema = 2
        status = 'PASS'
        mode = $Mode
        os = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture)
        powershell = $PSVersionTable.PSVersion.ToString()
        installer_path = $InstallerPath
        installer_sha256 = $installerSha
        installed_manifest = $manifest
        health = $health.Health
        base_url = $health.Url
        release_gate_python_source = $sourceGatePython
        release_gate_python = $gatePython
        release_gate_python_sha256 = $gatePythonSha
        release_gate_runtime_isolated = $true
    }
    Write-Json $envInfo (Join-Path $EvidenceDir 'environment.json')

    & $gatePython "$PSScriptRoot\ui_gate.py" --base-url $health.Url --evidence-dir $EvidenceDir --installer-sha256 $installerSha --expected-version $manifest.version --expected-build-id $manifest.build_id --expected-install-id $manifest.install_id --browser-channel $BrowserChannel
    if ($LASTEXITCODE -ne 0) { throw "Playwright UI gate failed" }
    & $gatePython "$PSScriptRoot\validate_outputs.py" --evidence-dir $EvidenceDir --installer-sha256 $installerSha
    if ($LASTEXITCODE -ne 0) { throw "Output validation failed" }

    $verdict = [ordered]@{
        schema = 1
        status = 'PASS'
        mode = $Mode
        installer_sha256 = $installerSha
        version = $manifest.version
        build_id = $manifest.build_id
        install_id = $manifest.install_id
        base_url = $health.Url
        embedded_selftest = 'PASS'
        playwright_ui = 'PASS'
        browser_channel = $BrowserChannel
        output_validation = 'PASS'
    }
    Write-Json $verdict (Join-Path $EvidenceDir $verdictName)
} catch {
    $failure = [ordered]@{ schema=1; status='FAIL'; mode=$Mode; installer_sha256=$installerSha; error=$_.Exception.Message }
    Write-Json $failure (Join-Path $EvidenceDir $verdictName)
    throw
} finally {
    if ($gateRuntimeRoot -and (Test-Path -LiteralPath $gateRuntimeRoot)) {
        Remove-Item -Recurse -Force -LiteralPath $gateRuntimeRoot -ErrorAction SilentlyContinue
    }
}
