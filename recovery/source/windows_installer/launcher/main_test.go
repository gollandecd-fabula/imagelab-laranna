package main

import (
	"os/exec"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestWithEnvOverridesDeduplicatesCaseInsensitiveKeys(t *testing.T) {
	result := withEnvOverrides(
		[]string{"Path=A", "PATH=B", "KEEP=1", "keep=2", "OTHER=3"},
		map[string]string{"PATH": "C", "IMAGELAB_INSTALL_ID": "install-1"},
	)
	counts := map[string]int{}
	values := map[string]string{}
	for _, entry := range result {
		parts := strings.SplitN(entry, "=", 2)
		key := strings.ToUpper(parts[0])
		counts[key]++
		if len(parts) == 2 {
			values[key] = parts[1]
		}
	}
	if counts["PATH"] != 1 || values["PATH"] != "C" {
		t.Fatalf("PATH override is not unique: %#v", result)
	}
	if counts["KEEP"] != 1 || values["KEEP"] != "1" {
		t.Fatalf("existing duplicate was not normalized: %#v", result)
	}
	if counts["IMAGELAB_INSTALL_ID"] != 1 || values["IMAGELAB_INSTALL_ID"] != "install-1" {
		t.Fatalf("install identity missing: %#v", result)
	}
}

func TestTerminateOwnedProcessStopsStartedProcess(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("Windows process-tree contract")
	}
	cmd := exec.Command("cmd.exe", "/C", "ping -n 30 127.0.0.1 >NUL")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	exit := make(chan error, 1)
	go func() { exit <- cmd.Wait() }()
	time.Sleep(250 * time.Millisecond)
	if err := terminateOwnedProcess(cmd, exit); err != nil {
		t.Fatal(err)
	}
	if cmd.ProcessState == nil || !cmd.ProcessState.Exited() {
		t.Fatalf("process was not reaped: %#v", cmd.ProcessState)
	}
}
