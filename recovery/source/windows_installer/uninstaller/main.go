package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"unsafe"
)

const appName = "ImageLab by LarannA"

type installManifest struct {
	App       string `json:"app"`
	Version   string `json:"version"`
	BuildID   string `json:"build_id"`
	InstallID string `json:"install_id"`
}

const uninstallScript = `$ErrorActionPreference = 'Stop'
$root = $env:IMAGELAB_UNINSTALL_ROOT
$desktop = $env:IMAGELAB_UNINSTALL_DESKTOP
$startMenu = $env:IMAGELAB_UNINSTALL_STARTMENU
$statusPath = $env:IMAGELAB_UNINSTALL_STATUS
$parentPid = [int]$env:IMAGELAB_UNINSTALL_PARENT_PID
$installId = $env:IMAGELAB_UNINSTALL_INSTALL_ID
$result = [ordered]@{schema=1; status='FAIL'; install_id=$installId; install_root=$root; error=$null}
try {
  Wait-Process -Id $parentPid -Timeout 45 -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase)
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 700
  $remaining = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase)
  })
  if ($remaining.Count -gt 0) { throw 'Процессы установки ImageLab не остановлены' }
  Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop
  if (Test-Path -LiteralPath $root) { throw 'Каталог установки остался после удаления' }
  Remove-Item -LiteralPath $desktop -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $startMenu -Force -ErrorAction SilentlyContinue
  Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageLabLarannA' -Recurse -Force -ErrorAction SilentlyContinue
  $result.status = 'PASS'
} catch {
  $result.error = $_.Exception.Message
} finally {
  $statusDir = Split-Path -Parent $statusPath
  New-Item -ItemType Directory -Path $statusDir -Force | Out-Null
  $result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statusPath -Encoding UTF8
}
Add-Type -AssemblyName PresentationFramework
if ($result.status -eq 'PASS') {
  [System.Windows.MessageBox]::Show('ImageLab удалён. Пользовательские проекты сохранены.','ImageLab by LarannA','OK','Information') | Out-Null
  exit 0
}
[System.Windows.MessageBox]::Show(('Удаление не завершено: ' + $result.error + [Environment]::NewLine + [Environment]::NewLine + 'Отчёт: ' + $statusPath),'ImageLab — ошибка удаления','OK','Error') | Out-Null
exit 1`

func messageBox(title, text string, flags uintptr) {
	user32 := syscall.NewLazyDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	proc.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
}

func envKey(entry string) string {
	if index := strings.IndexByte(entry, '='); index >= 0 {
		return strings.ToUpper(entry[:index])
	}
	return strings.ToUpper(entry)
}

func withEnvOverrides(base []string, overrides map[string]string) []string {
	overrideKeys := make(map[string]bool, len(overrides))
	ordered := make([]string, 0, len(overrides))
	for key := range overrides {
		overrideKeys[strings.ToUpper(key)] = true
		ordered = append(ordered, key)
	}
	sort.Slice(ordered, func(i, j int) bool { return strings.ToUpper(ordered[i]) < strings.ToUpper(ordered[j]) })
	result := make([]string, 0, len(base)+len(overrides))
	seen := map[string]bool{}
	for _, entry := range base {
		key := envKey(entry)
		if overrideKeys[key] || seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, entry)
	}
	for _, key := range ordered {
		result = append(result, key+"="+overrides[key])
	}
	return result
}

func validateInstallRoot(root string) (string, error) {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	clean := filepath.Clean(absolute)
	volumeRoot := filepath.Clean(filepath.VolumeName(clean) + string(os.PathSeparator))
	if clean == volumeRoot || filepath.Base(clean) != appName {
		return "", errors.New("небезопасный или неожиданный каталог установки")
	}
	return clean, nil
}

func readInstallManifest(installDir string) (installManifest, error) {
	data, err := os.ReadFile(filepath.Join(installDir, "install-manifest.json"))
	if err != nil {
		return installManifest{}, fmt.Errorf("не найден манифест установки: %w", err)
	}
	var manifest installManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return installManifest{}, fmt.Errorf("повреждён манифест установки: %w", err)
	}
	if manifest.App != appName || strings.TrimSpace(manifest.Version) == "" || strings.TrimSpace(manifest.BuildID) == "" || strings.TrimSpace(manifest.InstallID) == "" {
		return installManifest{}, errors.New("манифест не подтверждает установку ImageLab")
	}
	return manifest, nil
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		messageBox("ImageLab — ошибка удаления", err.Error(), 0x10)
		return
	}
	installDir, err := validateInstallRoot(filepath.Dir(exe))
	if err != nil {
		messageBox("ImageLab — ошибка удаления", "Удаление заблокировано: "+err.Error(), 0x10)
		return
	}
	manifest, err := readInstallManifest(installDir)
	if err != nil {
		messageBox("ImageLab — ошибка удаления", "Удаление заблокировано: "+err.Error(), 0x10)
		return
	}
	userProfile := os.Getenv("USERPROFILE")
	appData := os.Getenv("APPDATA")
	localAppData := os.Getenv("LOCALAPPDATA")
	if userProfile == "" || appData == "" || localAppData == "" {
		messageBox("ImageLab — ошибка удаления", "Не определены пользовательские каталоги Windows.", 0x10)
		return
	}
	desktop := filepath.Join(userProfile, "Desktop", "ImageLab by LarannA.lnk")
	startMenu := filepath.Join(appData, "Microsoft", "Windows", "Start Menu", "Programs", "ImageLab by LarannA.lnk")
	statusPath := filepath.Join(localAppData, "ImageLab by LarannA", "release-evidence", "uninstall-status.json")
	if err := os.MkdirAll(filepath.Dir(statusPath), 0755); err != nil {
		messageBox("ImageLab — ошибка удаления", "Не удалось подготовить отчёт удаления.\n\n"+err.Error(), 0x10)
		return
	}
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", uninstallScript)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	cmd.Env = withEnvOverrides(os.Environ(), map[string]string{
		"IMAGELAB_UNINSTALL_ROOT":       installDir,
		"IMAGELAB_UNINSTALL_DESKTOP":    desktop,
		"IMAGELAB_UNINSTALL_STARTMENU":  startMenu,
		"IMAGELAB_UNINSTALL_STATUS":     statusPath,
		"IMAGELAB_UNINSTALL_PARENT_PID": strconv.Itoa(os.Getpid()),
		"IMAGELAB_UNINSTALL_INSTALL_ID": manifest.InstallID,
	})
	if err := cmd.Start(); err != nil {
		messageBox("ImageLab — ошибка удаления", "Не удалось запустить удаление.\n\n"+err.Error(), 0x10)
		return
	}
	messageBox("ImageLab by LarannA", "Удаление запущено. После закрытия этого окна программа завершит удаление и покажет проверенный результат. Пользовательские проекты сохраняются.", 0x40)
}
