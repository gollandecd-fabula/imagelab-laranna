package main

import (
	"archive/zip"
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

//go:embed payload.zip
var payloadFS embed.FS

const (
	appName       = "ImageLab by LarannA"
	appVersion    = "1.4.7-recovery-candidate"
	buildID       = "REC-RT8-M6-20260724-04"
	pythonURL     = "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe"
	pythonSHA256  = "c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0"
	basePort      = 8765
	scanPortCount = 35
)

type installManifest struct {
	App           string            `json:"app"`
	Version       string            `json:"version"`
	BuildID       string            `json:"build_id"`
	InstallID     string            `json:"install_id"`
	PayloadSHA256 string            `json:"payload_sha256"`
	CriticalFiles map[string]string `json:"critical_files"`
	InstalledAt   string            `json:"installed_at"`
}

type healthResponse struct {
	Status    string `json:"status"`
	App       string `json:"app"`
	Version   string `json:"version"`
	BuildID   string `json:"build_id"`
	InstallID string `json:"install_id"`
}

func messageBox(title, text string, flags uintptr) {
	user32 := syscall.NewLazyDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	proc.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
}

func safeExtract(reader *zip.Reader, destination string) error {
	base, err := filepath.Abs(destination)
	if err != nil {
		return err
	}
	for _, file := range reader.File {
		clean := filepath.Clean(file.Name)
		if filepath.IsAbs(clean) || clean == "." || strings.HasPrefix(clean, "..") {
			return fmt.Errorf("unsafe archive path: %s", file.Name)
		}
		target := filepath.Join(base, clean)
		targetAbs, err := filepath.Abs(target)
		if err != nil || (targetAbs != base && !strings.HasPrefix(targetAbs, base+string(os.PathSeparator))) {
			return fmt.Errorf("archive traversal: %s", file.Name)
		}
		if file.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return err
		}
		in, err := file.Open()
		if err != nil {
			return err
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
		if err != nil {
			in.Close()
			return err
		}
		_, copyErr := io.Copy(out, in)
		closeErr := out.Close()
		in.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}

func extractBytes(data []byte, destination string) error {
	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return err
	}
	return safeExtract(reader, destination)
}

func downloadVerified(url, destination, expectedSHA256 string) error {
	client := &http.Client{Timeout: 20 * time.Minute}
	response, err := client.Get(url)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("download %s: HTTP %d", url, response.StatusCode)
	}
	temp := destination + ".part"
	file, err := os.OpenFile(temp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	hash := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(file, hash), io.LimitReader(response.Body, 500*1024*1024+1))
	closeErr := file.Close()
	if copyErr != nil {
		_ = os.Remove(temp)
		return copyErr
	}
	if closeErr != nil {
		_ = os.Remove(temp)
		return closeErr
	}
	if written > 500*1024*1024 {
		_ = os.Remove(temp)
		return errors.New("download exceeds safe size limit")
	}
	actual := hex.EncodeToString(hash.Sum(nil))
	if !strings.EqualFold(actual, expectedSHA256) {
		_ = os.Remove(temp)
		return fmt.Errorf("download SHA-256 mismatch: expected %s, got %s", expectedSHA256, actual)
	}
	return os.Rename(temp, destination)
}

func run(dir, command string, args ...string) error {
	cmd := exec.Command(command, args...)
	cmd.Dir = dir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = append(os.Environ(), "PIP_DISABLE_PIP_VERSION_CHECK=1", "PYTHONNOUSERSITE=1")
	return cmd.Run()
}

func randomInstallID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return hex.EncodeToString(buffer), nil
}

func sha256File(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func copyFile(source, destination string, mode os.FileMode) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(destination), 0755); err != nil {
		return err
	}
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode.Perm())
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(out, in)
	closeErr := out.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func copyDir(source, destination string) error {
	return filepath.Walk(source, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		relative, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		target := filepath.Join(destination, relative)
		if info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("runtime contains unsupported symlink: %s", path)
		}
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode().Perm())
		}
		return copyFile(path, target, info.Mode())
	})
}

func probeImageLab(port int) (healthResponse, bool) {
	client := &http.Client{Timeout: 550 * time.Millisecond}
	request, err := http.NewRequest(http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/api/health", port), nil)
	if err != nil {
		return healthResponse{}, false
	}
	request.Header.Set("Cache-Control", "no-cache")
	response, err := client.Do(request)
	if err != nil {
		return healthResponse{}, false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return healthResponse{}, false
	}
	var health healthResponse
	if err := json.NewDecoder(io.LimitReader(response.Body, 128*1024)).Decode(&health); err != nil {
		return healthResponse{}, false
	}
	return health, health.App == appName
}

func listenerPIDsPowerShell(port int) ([]int, error) {
	script := fmt.Sprintf(`Get-NetTCPConnection -State Listen -LocalPort %d -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique`, port)
	output, err := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script).CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("Get-NetTCPConnection: %w: %s", err, string(output))
	}
	var pids []int
	for _, field := range strings.Fields(string(output)) {
		pid, parseErr := strconv.Atoi(strings.TrimSpace(field))
		if parseErr == nil && pid > 0 {
			pids = append(pids, pid)
		}
	}
	return pids, nil
}

func listenerPIDsNetstat(port int) ([]int, error) {
	output, err := exec.Command("netstat.exe", "-ano", "-p", "tcp").CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("netstat: %w: %s", err, string(output))
	}
	needle := fmt.Sprintf(":%d", port)
	seen := map[int]bool{}
	var pids []int
	for _, line := range strings.Split(string(output), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 5 || !strings.EqualFold(fields[0], "TCP") || !strings.Contains(fields[1], needle) || !strings.EqualFold(fields[3], "LISTENING") {
			continue
		}
		pid, parseErr := strconv.Atoi(fields[4])
		if parseErr == nil && pid > 0 && !seen[pid] {
			seen[pid] = true
			pids = append(pids, pid)
		}
	}
	return pids, nil
}

func listenerPIDs(port int) ([]int, error) {
	pids, err := listenerPIDsPowerShell(port)
	if err == nil {
		return pids, nil
	}
	return listenerPIDsNetstat(port)
}

func killPID(pid int) {
	command := exec.Command("taskkill.exe", "/PID", strconv.Itoa(pid), "/T", "/F")
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	_ = command.Run()
}

func stopRunningImageLab(installDir string) error {
	// First identify servers by their own health endpoint. Only listeners that
	// identify as ImageLab are terminated, so unrelated localhost services are safe.
	for port := basePort; port < basePort+scanPortCount; port++ {
		if _, ok := probeImageLab(port); !ok {
			continue
		}
		pids, err := listenerPIDs(port)
		if err != nil {
			return fmt.Errorf("find ImageLab PID on port %d: %w", port, err)
		}
		for _, pid := range pids {
			killPID(pid)
		}
	}

	// Fallback for a process that has not reached /api/health yet but already
	// runs the private Python runtime from the managed installation directory.
	escaped := strings.ReplaceAll(installDir, "'", "''")
	script := fmt.Sprintf(`$root='%s'; Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and (($_.ExecutablePath -and $_.ExecutablePath.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase)) -or ($_.CommandLine -and $_.CommandLine -like '*bootstrap.py*' -and (($_.ExecutablePath -and $_.ExecutablePath -like '*ImageLab by LarannA*') -or $_.CommandLine -like '*ImageLab by LarannA*'))) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 700`, escaped)
	if err := run(filepath.Dir(installDir), "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script); err != nil {
		return fmt.Errorf("process sweep: %w", err)
	}

	deadline := time.Now().Add(12 * time.Second)
	for time.Now().Before(deadline) {
		remaining := false
		for port := basePort; port < basePort+scanPortCount; port++ {
			if _, ok := probeImageLab(port); ok {
				remaining = true
				break
			}
		}
		if !remaining {
			return nil
		}
		time.Sleep(300 * time.Millisecond)
	}
	return errors.New("предыдущий сервер ImageLab не остановился")
}

func createShortcut(target, shortcut, workDir string) error {
	script := fmt.Sprintf(`$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut('%s'); $s.TargetPath='%s'; $s.WorkingDirectory='%s'; $s.Description='ImageLab by LarannA'; $s.Save()`, strings.ReplaceAll(shortcut, "'", "''"), strings.ReplaceAll(target, "'", "''"), strings.ReplaceAll(workDir, "'", "''"))
	return run(workDir, "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
}

func runtimeWorks(python, root string) bool {
	cmd := exec.Command(python, "-I", "-c", "import sys; assert sys.version_info[:2] == (3, 13); print(sys.executable)")
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONNOUSERSITE=1")
	return cmd.Run() == nil
}

func ensureRuntime(stagingDir, currentInstallDir string) error {
	runtimeDir := filepath.Join(stagingDir, "runtime")
	python := filepath.Join(runtimeDir, "python.exe")
	runtimeMarker := filepath.Join(runtimeDir, ".imagelab-python-3.13.14")
	currentRuntime := filepath.Join(currentInstallDir, "runtime")
	currentMarker := filepath.Join(currentRuntime, ".imagelab-python-3.13.14")
	if marker, err := os.ReadFile(currentMarker); err == nil && strings.TrimSpace(string(marker)) == pythonSHA256 {
		fmt.Println("[2/11] Копирование проверенного приватного Python runtime в staging...")
		if err := copyDir(currentRuntime, runtimeDir); err == nil {
			if _, statErr := os.Stat(python); statErr == nil && runtimeWorks(python, stagingDir) {
				return nil
			}
		}
		_ = os.RemoveAll(runtimeDir)
	}

	fmt.Println("[2/11] Загрузка и проверка официального Python runtime...")
	installerPath := filepath.Join(os.TempDir(), "imagelab-python-3.13.14-amd64.exe")
	if err := downloadVerified(pythonURL, installerPath, pythonSHA256); err != nil {
		return err
	}
	_ = os.RemoveAll(runtimeDir)
	if err := os.MkdirAll(runtimeDir, 0755); err != nil {
		return err
	}
	args := []string{"/quiet", "InstallAllUsers=0", "TargetDir=" + runtimeDir, "PrependPath=0", "Include_launcher=0", "Include_pip=1", "Include_test=0", "Include_doc=0", "Include_tcltk=0", "Include_tools=0", "Include_dev=0", "Shortcuts=0"}
	if err := run(stagingDir, installerPath, args...); err != nil {
		return fmt.Errorf("Python installer: %w", err)
	}
	_ = os.Remove(installerPath)
	if _, err := os.Stat(python); err != nil {
		return fmt.Errorf("Python runtime was not installed: %w", err)
	}
	if !runtimeWorks(python, stagingDir) {
		return errors.New("installed Python runtime failed its isolated startup check")
	}
	return os.WriteFile(runtimeMarker, []byte(pythonSHA256+"\n"), 0644)
}

func verifyModels(installDir, installID string) error {
	command := fmt.Sprintf(`import importlib.metadata as m; expected={'fastapi':'0.128.2','starlette':'0.50.0','pydantic':'2.13.4','pydantic-core':'2.46.4','annotated-types':'0.7.0','annotated-doc':'0.0.4','typing-extensions':'4.15.0','typing-inspection':'0.4.2','anyio':'4.13.0','idna':'3.17','uvicorn':'0.48.0','click':'8.1.8','h11':'0.16.0','colorama':'0.4.6','python-multipart':'0.0.31','Pillow':'12.3.0','numpy':'2.3.5','opencv-python-headless':'4.13.0.92'}; actual={k:m.version(k) for k in expected}; assert actual==expected,(actual,expected); from app.config import settings; assert settings.app_version==%q; assert settings.build_id==%q; assert settings.install_id==%q; from app.main import app; from app.ai.runtime import get_ai_engine; h=get_ai_engine().health(); assert h['status']=='ready'; assert len(h['models'])==11; print('DEPENDENCIES, IDENTITY AND AI MODELS VERIFIED',actual,len(h['models']))`, appVersion, buildID, installID)
	python := filepath.Join(installDir, "runtime", "python.exe")
	cmd := exec.Command(python, "-c", command)
	cmd.Dir = installDir
	cmd.Env = append(os.Environ(),
		"IMAGELAB_DATA_DIR="+filepath.Join(os.Getenv("LOCALAPPDATA"), "ImageLab by LarannA", "data"),
		"IMAGELAB_STATIC_DIR="+filepath.Join(installDir, "app", "static"),
		"IMAGELAB_AI_MODEL_DIR="+filepath.Join(installDir, "models"),
		"PYTHONPATH="+installDir+";"+filepath.Join(installDir, "runtime", "Lib", "site-packages"),
		"PYTHONNOUSERSITE=1",
		"IMAGELAB_INSTALL_ID="+installID,
	)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("environment verification: %w\n%s", err, string(output))
	}
	fmt.Print(string(output))
	return nil
}

func runReleaseSelfTest(root, installID, phase, outputPath string) error {
	python := filepath.Join(root, "runtime", "python.exe")
	if _, err := os.Stat(filepath.Join(root, "app", "release_selftest.py")); err != nil {
		return fmt.Errorf("release self-test module missing: %w", err)
	}
	testData, err := os.MkdirTemp("", "imagelab-release-selftest-"+phase+"-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(testData)
	if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
		return err
	}
	cmd := exec.Command(python, "-m", "app.release_selftest", "--output", outputPath)
	cmd.Dir = root
	cmd.Env = append(os.Environ(),
		"IMAGELAB_DATA_DIR="+filepath.Join(testData, "data"),
		"IMAGELAB_STATIC_DIR="+filepath.Join(root, "app", "static"),
		"IMAGELAB_AI_MODEL_DIR="+filepath.Join(root, "models"),
		"PYTHONPATH="+root+";"+filepath.Join(root, "runtime", "Lib", "site-packages"),
		"PYTHONNOUSERSITE=1",
		"IMAGELAB_INSTALL_ID="+installID,
	)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s release self-test: %w\n%s", phase, err, string(output))
	}
	var verdict struct {
		Status    string `json:"status"`
		Version   string `json:"version"`
		BuildID   string `json:"build_id"`
		InstallID string `json:"install_id"`
	}
	data, readErr := os.ReadFile(outputPath)
	if readErr != nil {
		return fmt.Errorf("read %s self-test verdict: %w", phase, readErr)
	}
	if err := json.Unmarshal(data, &verdict); err != nil {
		return fmt.Errorf("parse %s self-test verdict: %w", phase, err)
	}
	if verdict.Status != "PASS" || verdict.Version != appVersion || verdict.BuildID != buildID || verdict.InstallID != installID {
		return fmt.Errorf("%s self-test identity/status mismatch: %+v", phase, verdict)
	}
	fmt.Print(string(output))
	return nil
}

func faultRequested(point string) bool {
	return strings.EqualFold(strings.TrimSpace(os.Getenv("IMAGELAB_INSTALLER_FAULT")), point)
}

func writeInstallManifest(stagingDir, installID, payloadSHA string) (installManifest, error) {
	criticalNames := []string{
		"ImageLab.exe",
		"bootstrap.py",
		"requirements.txt",
		filepath.Join("app", "config.py"),
		filepath.Join("app", "main.py"),
		filepath.Join("app", "release_selftest.py"),
		filepath.Join("app", "static", "index.html"),
		filepath.Join("app", "static", "app.js"),
		filepath.Join("app", "static", "styles.css"),
		filepath.Join("models", "manifest.json"),
	}
	critical := make(map[string]string, len(criticalNames))
	for _, relative := range criticalNames {
		hash, err := sha256File(filepath.Join(stagingDir, relative))
		if err != nil {
			return installManifest{}, fmt.Errorf("critical file %s: %w", relative, err)
		}
		critical[filepath.ToSlash(relative)] = hash
	}
	manifest := installManifest{
		App:           appName,
		Version:       appVersion,
		BuildID:       buildID,
		InstallID:     installID,
		PayloadSHA256: payloadSHA,
		CriticalFiles: critical,
		InstalledAt:   time.Now().UTC().Format(time.RFC3339),
	}
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return installManifest{}, err
	}
	if err := os.WriteFile(filepath.Join(stagingDir, "install-manifest.json"), append(data, '\n'), 0644); err != nil {
		return installManifest{}, err
	}
	return manifest, nil
}

func verifyInstallManifest(root string, expected installManifest) error {
	data, err := os.ReadFile(filepath.Join(root, "install-manifest.json"))
	if err != nil {
		return err
	}
	var actual installManifest
	if err := json.Unmarshal(data, &actual); err != nil {
		return err
	}
	if actual.App != expected.App || actual.Version != expected.Version || actual.BuildID != expected.BuildID || actual.InstallID != expected.InstallID || actual.PayloadSHA256 != expected.PayloadSHA256 {
		return errors.New("install manifest identity mismatch")
	}
	for relative, expectedHash := range actual.CriticalFiles {
		actualHash, err := sha256File(filepath.Join(root, filepath.FromSlash(relative)))
		if err != nil {
			return err
		}
		if !strings.EqualFold(actualHash, expectedHash) {
			return fmt.Errorf("critical file hash mismatch: %s", relative)
		}
	}
	return nil
}

func renameWithRetry(oldPath, newPath string) error {
	var last error
	for attempt := 0; attempt < 12; attempt++ {
		if err := os.Rename(oldPath, newPath); err == nil {
			return nil
		} else {
			last = err
		}
		time.Sleep(time.Duration(250+attempt*100) * time.Millisecond)
	}
	return last
}

func promoteAtomic(stagingDir, installDir, backupDir string) (bool, error) {
	_ = os.RemoveAll(backupDir)
	hadPrevious := false
	if _, err := os.Stat(installDir); err == nil {
		hadPrevious = true
		if err := renameWithRetry(installDir, backupDir); err != nil {
			return false, fmt.Errorf("backup previous installation: %w", err)
		}
	}
	if err := renameWithRetry(stagingDir, installDir); err != nil {
		if hadPrevious {
			_ = renameWithRetry(backupDir, installDir)
		}
		return hadPrevious, fmt.Errorf("promote staging installation: %w", err)
	}
	return hadPrevious, nil
}

func rollbackPromotion(installDir, backupDir string, hadPrevious bool) error {
	if err := stopRunningImageLab(installDir); err != nil {
		return err
	}
	failedDir := installDir + ".failed-" + strconv.FormatInt(time.Now().Unix(), 10)
	if _, err := os.Stat(installDir); err == nil {
		if renameErr := renameWithRetry(installDir, failedDir); renameErr != nil {
			if removeErr := os.RemoveAll(installDir); removeErr != nil {
				return fmt.Errorf("remove failed installation: %w", removeErr)
			}
		}
	}
	if hadPrevious {
		if err := renameWithRetry(backupDir, installDir); err != nil {
			return fmt.Errorf("restore previous installation: %w", err)
		}
	}
	_ = os.RemoveAll(failedDir)
	return nil
}

func exactHealth(port int, installID string) bool {
	health, ok := probeImageLab(port)
	return ok && health.Status == "ok" && health.Version == appVersion && health.BuildID == buildID && health.InstallID == installID
}

func waitForExactHealth(installID string) (int, error) {
	deadline := time.Now().Add(90 * time.Second)
	for time.Now().Before(deadline) {
		for port := basePort; port < basePort+scanPortCount; port++ {
			if exactHealth(port, installID) {
				return port, nil
			}
		}
		time.Sleep(350 * time.Millisecond)
	}
	return 0, errors.New("новая установка не подтвердила точную версию/build/install ID за 90 секунд")
}

func writeUninstallRegistry(installDir string) error {
	uninstall := filepath.Join(installDir, "Uninstall.exe")
	key := `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageLabLarannA`
	commands := [][]string{
		{"add", key, "/v", "DisplayName", "/t", "REG_SZ", "/d", appName, "/f"},
		{"add", key, "/v", "DisplayVersion", "/t", "REG_SZ", "/d", appVersion, "/f"},
		{"add", key, "/v", "InstallLocation", "/t", "REG_SZ", "/d", installDir, "/f"},
		{"add", key, "/v", "UninstallString", "/t", "REG_SZ", "/d", uninstall, "/f"},
	}
	for _, args := range commands {
		if err := run(installDir, "reg.exe", args...); err != nil {
			return err
		}
	}
	return nil
}

func install() error {
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return errors.New("LOCALAPPDATA is not defined")
	}
	installDir := filepath.Join(local, "Programs", "ImageLab by LarannA")
	dataDir := filepath.Join(local, "ImageLab by LarannA", "data")
	if err := os.MkdirAll(filepath.Dir(installDir), 0755); err != nil {
		return err
	}
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		return err
	}

	installID, err := randomInstallID()
	if err != nil {
		return fmt.Errorf("generate install ID: %w", err)
	}
	stagingDir := installDir + ".staging-" + installID[:12]
	backupDir := installDir + ".backup"
	_ = os.RemoveAll(stagingDir)
	if err := os.MkdirAll(stagingDir, 0755); err != nil {
		return err
	}
	defer os.RemoveAll(stagingDir)

	fmt.Println("[1/11] Распаковка новой версии в изолированный staging-каталог...")
	payload, err := payloadFS.ReadFile("payload.zip")
	if err != nil {
		return err
	}
	payloadSum := sha256.Sum256(payload)
	payloadSHA := hex.EncodeToString(payloadSum[:])
	fmt.Println("Payload SHA-256:", payloadSHA)
	if err := extractBytes(payload, stagingDir); err != nil {
		return err
	}

	if err := ensureRuntime(stagingDir, installDir); err != nil {
		return err
	}
	python := filepath.Join(stagingDir, "runtime", "python.exe")
	fmt.Println("[3/11] Проверка pip в staging...")
	if err := run(stagingDir, python, "-m", "pip", "--version"); err != nil {
		return fmt.Errorf("pip unavailable: %w", err)
	}
	fmt.Println("[4/11] Установка точных зависимостей в staging...")
	if err := run(stagingDir, python, "-m", "pip", "install", "-r", filepath.Join(stagingDir, "requirements.txt"), "--only-binary=:all:", "--no-deps", "--no-warn-script-location"); err != nil {
		return fmt.Errorf("dependencies: %w", err)
	}
	if err := run(stagingDir, python, "-m", "pip", "check"); err != nil {
		return fmt.Errorf("dependency consistency: %w", err)
	}

	fmt.Println("[5/11] Проверка кода, зависимостей, AI-runtime и идентичности staging...")
	if err := verifyModels(stagingDir, installID); err != nil {
		return err
	}
	preinstallEvidence := filepath.Join(stagingDir, "release-evidence", "preinstall-selftest.json")
	fmt.Println("[6/11] Производственный self-test новой версии до изменения текущей установки...")
	if err := runReleaseSelfTest(stagingDir, installID, "preinstall", preinstallEvidence); err != nil {
		return err
	}
	manifest, err := writeInstallManifest(stagingDir, installID, payloadSHA)
	if err != nil {
		return fmt.Errorf("write install manifest: %w", err)
	}
	if err := verifyInstallManifest(stagingDir, manifest); err != nil {
		return fmt.Errorf("verify staging manifest: %w", err)
	}

	fmt.Println("[7/11] Остановка всех ранее запущенных экземпляров ImageLab...")
	if err := stopRunningImageLab(installDir); err != nil {
		return fmt.Errorf("stop previous ImageLab: %w", err)
	}

	fmt.Println("[8/11] Атомарное переключение на новую версию...")
	hadPrevious, err := promoteAtomic(stagingDir, installDir, backupDir)
	if err != nil {
		return err
	}
	if err := verifyInstallManifest(installDir, manifest); err != nil {
		_ = rollbackPromotion(installDir, backupDir, hadPrevious)
		return fmt.Errorf("post-promotion integrity verification: %w", err)
	}
	if faultRequested("after_promotion") {
		rollbackErr := rollbackPromotion(installDir, backupDir, hadPrevious)
		if rollbackErr != nil {
			return fmt.Errorf("injected failure after promotion; rollback failed: %w", rollbackErr)
		}
		return errors.New("injected failure after promotion; previous installation restored")
	}

	postinstallEvidence := filepath.Join(os.Getenv("LOCALAPPDATA"), "ImageLab by LarannA", "release-evidence", "postinstall-selftest.json")
	fmt.Println("[9/11] Повторный производственный self-test уже установленной версии...")
	if err := runReleaseSelfTest(installDir, installID, "postinstall", postinstallEvidence); err != nil {
		rollbackErr := rollbackPromotion(installDir, backupDir, hadPrevious)
		if rollbackErr != nil {
			return fmt.Errorf("%v; rollback failed: %w", err, rollbackErr)
		}
		return fmt.Errorf("%v; previous installation restored", err)
	}

	launcher := filepath.Join(installDir, "ImageLab.exe")
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop", "ImageLab by LarannA.lnk")
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "ImageLab by LarannA.lnk")
	if err := os.MkdirAll(filepath.Dir(startMenu), 0755); err != nil {
		_ = rollbackPromotion(installDir, backupDir, hadPrevious)
		return fmt.Errorf("start menu directory: %w", err)
	}
	if err := createShortcut(launcher, desktop, installDir); err != nil {
		_ = rollbackPromotion(installDir, backupDir, hadPrevious)
		return fmt.Errorf("desktop shortcut: %w", err)
	}
	if err := createShortcut(launcher, startMenu, installDir); err != nil {
		_ = rollbackPromotion(installDir, backupDir, hadPrevious)
		return fmt.Errorf("start menu shortcut: %w", err)
	}

	fmt.Println("[10/11] Запуск новой установки и ожидание точного health identity...")
	command := exec.Command(launcher)
	command.Env = append(os.Environ(), "IMAGELAB_INSTALLER_EXPECTED_INSTALL_ID="+installID)
	if os.Getenv("IMAGELAB_INSTALLER_CI") == "1" {
		command.Env = append(command.Env, "IMAGELAB_EXTERNAL_BROWSER=1")
	}
	if err := command.Start(); err != nil {
		_ = rollbackPromotion(installDir, backupDir, hadPrevious)
		return fmt.Errorf("launch ImageLab: %w", err)
	}
	port, err := waitForExactHealth(installID)
	if err != nil {
		rollbackErr := rollbackPromotion(installDir, backupDir, hadPrevious)
		if rollbackErr != nil {
			return fmt.Errorf("%v; rollback failed: %w", err, rollbackErr)
		}
		return fmt.Errorf("%v; previous installation restored", err)
	}

	fmt.Printf("[11/11] Новая установка подтверждена на 127.0.0.1:%d.\n", port)
	if err := writeUninstallRegistry(installDir); err != nil {
		rollbackErr := rollbackPromotion(installDir, backupDir, hadPrevious)
		if rollbackErr != nil {
			return fmt.Errorf("uninstall registry: %v; rollback failed: %w", err, rollbackErr)
		}
		return fmt.Errorf("uninstall registry: %v; previous installation restored", err)
	}
	if removeErr := os.RemoveAll(backupDir); removeErr != nil {
		fmt.Println("Предупреждение: резервная копия предыдущей версии не удалена:", removeErr)
	}
	fmt.Printf("Установка завершена: version=%s build=%s install=%s\n", appVersion, buildID, installID)
	return nil
}

func main() {
	ciMode := os.Getenv("IMAGELAB_INSTALLER_CI") == "1"
	if err := install(); err != nil {
		fmt.Fprintln(os.Stderr, "ОШИБКА:", err)
		if !ciMode {
			messageBox("ImageLab — ошибка установки", "Установка не завершена.\n\n"+err.Error(), 0x10)
		}
		os.Exit(1)
	}
	if !ciMode {
		messageBox("ImageLab by LarannA", "Новая версия установлена и подтверждена работающим сервером. Старый процесс не используется.", 0x40)
	}
}
