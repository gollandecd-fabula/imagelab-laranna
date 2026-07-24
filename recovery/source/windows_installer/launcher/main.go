package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	appName    = "ImageLab by LarannA"
	appVersion = "1.4.4-recovery-candidate"
	buildID    = "REC-RT8-M6-20260724-01"
	basePort   = 8765
	portCount  = 10
)

type installManifest struct {
	App           string            `json:"app"`
	Version       string            `json:"version"`
	BuildID       string            `json:"build_id"`
	InstallID     string            `json:"install_id"`
	PayloadSHA256 string            `json:"payload_sha256"`
	CriticalFiles map[string]string `json:"critical_files"`
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

func fail(message string, err error) {
	text := message
	if err != nil {
		text += "\n\n" + err.Error()
	}
	messageBox("ImageLab — ошибка запуска", text, 0x10)
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

func readAndVerifyManifest(installDir string) (installManifest, error) {
	path := filepath.Join(installDir, "install-manifest.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return installManifest{}, fmt.Errorf("не найден манифест установки: %w", err)
	}
	var manifest installManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return installManifest{}, fmt.Errorf("повреждён манифест установки: %w", err)
	}
	if manifest.App != appName || manifest.Version != appVersion || manifest.BuildID != buildID || strings.TrimSpace(manifest.InstallID) == "" {
		return installManifest{}, fmt.Errorf(
			"несовпадение сборки: manifest=%s/%s/%s, launcher=%s/%s/%s",
			manifest.App, manifest.Version, manifest.BuildID, appName, appVersion, buildID,
		)
	}
	if len(manifest.CriticalFiles) == 0 {
		return installManifest{}, fmt.Errorf("манифест не содержит контрольных сумм")
	}
	base, err := filepath.Abs(installDir)
	if err != nil {
		return installManifest{}, err
	}
	for relative, expected := range manifest.CriticalFiles {
		clean := filepath.Clean(relative)
		if filepath.IsAbs(clean) || clean == "." || strings.HasPrefix(clean, "..") {
			return installManifest{}, fmt.Errorf("опасный путь в манифесте: %s", relative)
		}
		target := filepath.Join(base, clean)
		targetAbs, err := filepath.Abs(target)
		if err != nil || (targetAbs != base && !strings.HasPrefix(targetAbs, base+string(os.PathSeparator))) {
			return installManifest{}, fmt.Errorf("путь выходит за каталог установки: %s", relative)
		}
		actual, err := sha256File(targetAbs)
		if err != nil {
			return installManifest{}, fmt.Errorf("не удалось проверить %s: %w", relative, err)
		}
		if !strings.EqualFold(actual, expected) {
			return installManifest{}, fmt.Errorf("контрольная сумма не совпадает: %s", relative)
		}
	}
	return manifest, nil
}

func exactHealth(port int, manifest installManifest) bool {
	client := &http.Client{Timeout: 700 * time.Millisecond}
	request, err := http.NewRequest(http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/api/health", port), nil)
	if err != nil {
		return false
	}
	request.Header.Set("Cache-Control", "no-cache")
	response, err := client.Do(request)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false
	}
	var health healthResponse
	decoder := json.NewDecoder(io.LimitReader(response.Body, 128*1024))
	if err := decoder.Decode(&health); err != nil {
		return false
	}
	return health.Status == "ok" && health.App == appName && health.Version == appVersion && health.BuildID == buildID && health.InstallID == manifest.InstallID
}

func findExactHealth(manifest installManifest) (int, bool) {
	for port := basePort; port < basePort+portCount; port++ {
		if exactHealth(port, manifest) {
			return port, true
		}
	}
	return 0, false
}

func waitForExactHealth(manifest installManifest, processExit <-chan error) error {
	deadline := time.NewTimer(75 * time.Second)
	defer deadline.Stop()
	ticker := time.NewTicker(300 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			if _, ok := findExactHealth(manifest); ok {
				return nil
			}
		case err := <-processExit:
			if _, ok := findExactHealth(manifest); ok {
				return nil
			}
			if err == nil {
				return fmt.Errorf("процесс запуска завершился до готовности сервера")
			}
			return fmt.Errorf("процесс запуска завершился: %w", err)
		case <-deadline.C:
			return fmt.Errorf("новая версия не ответила за 75 секунд")
		}
	}
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		fail("Не удалось определить каталог ImageLab.", err)
		return
	}
	installDir := filepath.Dir(exe)
	manifest, err := readAndVerifyManifest(installDir)
	if err != nil {
		fail("Установка ImageLab повреждена, смешана со старой версией или не завершена. Переустановите программу.", err)
		return
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		fail("Переменная LOCALAPPDATA не определена.", nil)
		return
	}
	dataRoot := filepath.Join(local, "ImageLab by LarannA")
	dataDir := filepath.Join(dataRoot, "data")
	logDir := filepath.Join(dataRoot, "logs")
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		fail("Не удалось создать каталог пользовательских данных.", err)
		return
	}
	if err := os.MkdirAll(logDir, 0755); err != nil {
		fail("Не удалось создать каталог журналов.", err)
		return
	}

	python := filepath.Join(installDir, "runtime", "python.exe")
	bootstrap := filepath.Join(installDir, "bootstrap.py")
	for _, required := range []string{python, bootstrap, filepath.Join(installDir, "app", "main.py"), filepath.Join(installDir, "models", "manifest.json")} {
		if info, statErr := os.Stat(required); statErr != nil || info.IsDir() {
			fail("Установка ImageLab повреждена или не завершена. Переустановите программу.", fmt.Errorf("отсутствует файл: %s", required))
			return
		}
	}

	if _, ok := findExactHealth(manifest); ok {
		// Bootstrap is still executed below because it opens the exact instance in
		// the browser and independently verifies the launcher identity.
	}

	logPath := filepath.Join(logDir, "launcher.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		fail("Не удалось открыть журнал запуска.", err)
		return
	}
	_, _ = fmt.Fprintf(logFile, "\n[%s] launcher version=%s build=%s install=%s root=%s\n", time.Now().Format(time.RFC3339), appVersion, buildID, manifest.InstallID, installDir)

	cmd := exec.Command(python, bootstrap)
	cmd.Dir = installDir
	cmd.Env = append(os.Environ(),
		"IMAGELAB_DATA_DIR="+dataDir,
		"IMAGELAB_STATIC_DIR="+filepath.Join(installDir, "app", "static"),
		"IMAGELAB_AI_MODEL_DIR="+filepath.Join(installDir, "models"),
		"PYTHONPATH="+installDir+";"+filepath.Join(installDir, "runtime", "Lib", "site-packages"),
		"PYTHONNOUSERSITE=1",
		"IMAGELAB_EXPECTED_VERSION="+appVersion,
		"IMAGELAB_EXPECTED_BUILD_ID="+buildID,
		"IMAGELAB_EXPECTED_INSTALL_ID="+manifest.InstallID,
		"IMAGELAB_INSTALL_ID="+manifest.InstallID,
	)
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x00000008}
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		fail("ImageLab не удалось запустить. Подробности сохранены в журнале:\n"+logPath, err)
		return
	}
	exit := make(chan error, 1)
	go func() { exit <- cmd.Wait() }()
	if err := waitForExactHealth(manifest, exit); err != nil {
		_, _ = fmt.Fprintf(logFile, "startup verification failed: %v\n", err)
		_ = logFile.Close()
		fail("Запущенный сервер не подтвердил точную новую версию. Подробности сохранены в журнале:\n"+logPath, err)
		return
	}
	_, _ = fmt.Fprintln(logFile, "startup identity verified")
	_ = logFile.Close()
}
