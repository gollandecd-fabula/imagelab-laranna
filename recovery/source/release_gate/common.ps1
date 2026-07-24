Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-ImageLabInstallDir {
    return Join-Path $env:LOCALAPPDATA 'Programs\ImageLab by LarannA'
}

function Get-ImageLabManifest {
    $path = Join-Path (Get-ImageLabInstallDir) 'install-manifest.json'
    if (-not (Test-Path -LiteralPath $path)) { throw "Install manifest not found: $path" }
    return Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
}

function Find-ImageLabHealth([object]$Manifest, [int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($port in 8765..8799) {
            try {
                $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2 -Headers @{ 'Cache-Control'='no-cache' }
                if ($health.status -eq 'ok' -and $health.version -eq $Manifest.version -and $health.build_id -eq $Manifest.build_id -and $health.install_id -eq $Manifest.install_id) {
                    return [PSCustomObject]@{ Port=$port; Url="http://127.0.0.1:$port"; Health=$health }
                }
            } catch { }
        }
        Start-Sleep -Milliseconds 400
    }
    throw "Exact ImageLab health identity not found within $TimeoutSeconds seconds"
}

function Stop-ImageLabProcesses {
    foreach ($port in 8765..8799) {
        try {
            $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            foreach ($connection in $connections) {
                Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -in @('ImageLab.exe','python.exe','pythonw.exe')) -and ($_.CommandLine -like '*ImageLab by LarannA*' -or $_.ExecutablePath -like '*ImageLab by LarannA*')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Invoke-Installer([string]$InstallerPath, [string]$EvidenceDir, [string]$Prefix, [string]$Fault = '') {
    New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
    $stdout = Join-Path $EvidenceDir "$Prefix-stdout.log"
    $stderr = Join-Path $EvidenceDir "$Prefix-stderr.log"
    $oldCi = $env:IMAGELAB_INSTALLER_CI
    $oldFault = $env:IMAGELAB_INSTALLER_FAULT
    try {
        $env:IMAGELAB_INSTALLER_CI = '1'
        if ($Fault) { $env:IMAGELAB_INSTALLER_FAULT = $Fault } else { Remove-Item Env:IMAGELAB_INSTALLER_FAULT -ErrorAction SilentlyContinue }
        $process = Start-Process -FilePath $InstallerPath -WorkingDirectory (Split-Path -Parent $InstallerPath) -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        return $process.ExitCode
    } finally {
        if ($null -eq $oldCi) { Remove-Item Env:IMAGELAB_INSTALLER_CI -ErrorAction SilentlyContinue } else { $env:IMAGELAB_INSTALLER_CI = $oldCi }
        if ($null -eq $oldFault) { Remove-Item Env:IMAGELAB_INSTALLER_FAULT -ErrorAction SilentlyContinue } else { $env:IMAGELAB_INSTALLER_FAULT = $oldFault }
    }
}

function Write-Json([object]$Value, [string]$Path) {
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding utf8
}
