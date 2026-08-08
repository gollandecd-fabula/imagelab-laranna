package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

func messageBox(title, text string, flags uintptr) {
	user32 := syscall.NewLazyDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	proc.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		messageBox("ImageLab — ошибка удаления", err.Error(), 0x10)
		return
	}
	installDir := filepath.Dir(exe)
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop", "ImageLab by LarannA.lnk")
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "ImageLab by LarannA.lnk")
	script := fmt.Sprintf(`Start-Sleep -Seconds 2; Remove-Item -LiteralPath '%s' -Recurse -Force -ErrorAction Stop; Remove-Item -LiteralPath '%s' -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath '%s' -Force -ErrorAction SilentlyContinue; Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageLabLarannA' -Recurse -Force -ErrorAction SilentlyContinue`, installDir, desktop, startMenu)
	cmd := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
	if err := cmd.Start(); err != nil {
		messageBox("ImageLab — ошибка удаления", "Не удалось запустить удаление.\n\n"+err.Error(), 0x10)
		return
	}
	messageBox("ImageLab by LarannA", "Удаление запущено. Пользовательские проекты сохраняются.", 0x40)
}
