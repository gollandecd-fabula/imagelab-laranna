package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWithEnvOverridesKeepsOneValuePerKey(t *testing.T) {
	result := withEnvOverrides([]string{"Path=A", "PATH=B", "KEEP=1"}, map[string]string{"PATH": "C"})
	pathCount := 0
	for _, entry := range result {
		if strings.EqualFold(strings.SplitN(entry, "=", 2)[0], "PATH") {
			pathCount++
			if entry != "PATH=C" {
				t.Fatalf("unexpected PATH value: %q", entry)
			}
		}
	}
	if pathCount != 1 {
		t.Fatalf("expected one PATH entry, got %#v", result)
	}
}

func TestValidateInstallRootRejectsDangerousOrUnexpectedRoots(t *testing.T) {
	volumeRoot := filepath.VolumeName(os.TempDir()) + string(os.PathSeparator)
	if _, err := validateInstallRoot(volumeRoot); err == nil {
		t.Fatal("volume root must be rejected")
	}
	if _, err := validateInstallRoot(filepath.Join(os.TempDir(), "Not ImageLab")); err == nil {
		t.Fatal("unexpected directory name must be rejected")
	}
	valid := filepath.Join(os.TempDir(), appName)
	resolved, err := validateInstallRoot(valid)
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Base(resolved) != appName {
		t.Fatalf("unexpected resolved root: %s", resolved)
	}
}

func TestReadInstallManifestRequiresImageLabIdentity(t *testing.T) {
	root := filepath.Join(t.TempDir(), appName)
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	valid := `{"app":"ImageLab by LarannA","version":"1","build_id":"b","install_id":"i"}`
	if err := os.WriteFile(filepath.Join(root, "install-manifest.json"), []byte(valid), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest, err := readInstallManifest(root)
	if err != nil || manifest.InstallID != "i" {
		t.Fatalf("valid manifest rejected: %#v %v", manifest, err)
	}
	invalid := `{"app":"Other","version":"1","build_id":"b","install_id":"i"}`
	if err := os.WriteFile(filepath.Join(root, "install-manifest.json"), []byte(invalid), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := readInstallManifest(root); err == nil {
		t.Fatal("foreign manifest must be rejected")
	}
}

func TestPowerShellUsesEnvironmentPathsAndWritesVerifiedStatus(t *testing.T) {
	for _, token := range []string{
		"IMAGELAB_UNINSTALL_ROOT",
		"IMAGELAB_UNINSTALL_STATUS",
		"Wait-Process",
		"ExecutablePath.StartsWith",
		"Test-Path -LiteralPath $root",
		"ConvertTo-Json",
		"$result.status = 'PASS'",
	} {
		if !strings.Contains(uninstallScript, token) {
			t.Fatalf("missing uninstall contract %q", token)
		}
	}
	if strings.Contains(uninstallScript, "fmt.Sprintf") {
		t.Fatal("paths must not be interpolated into PowerShell source")
	}
}
