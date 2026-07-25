package main

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func zipReader(t *testing.T, entries map[string]string) *zip.Reader {
	t.Helper()
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	for name, body := range entries {
		header := &zip.FileHeader{Name: name, Method: zip.Deflate}
		header.SetMode(0o600)
		entry, err := writer.CreateHeader(header)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write([]byte(body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	reader, err := zip.NewReader(bytes.NewReader(buffer.Bytes()), int64(buffer.Len()))
	if err != nil {
		t.Fatal(err)
	}
	return reader
}

func TestArchiveEntryKeyRejectsWindowsUnsafeNames(t *testing.T) {
	unsafe := []string{
		"../escape.txt",
		"/absolute.txt",
		`folder\\escape.txt`,
		"folder/file.txt:stream",
		"folder/CON.txt",
		"folder/com1.log",
		"folder/trailing. ",
		"folder/trailing.",
	}
	for _, name := range unsafe {
		if _, err := archiveEntryKey(name); err == nil {
			t.Fatalf("expected unsafe path rejection for %q", name)
		}
	}
}

func TestValidateArchiveEntriesRejectsCaseCollisionAndSymlink(t *testing.T) {
	if err := validateArchiveEntries(zipReader(t, map[string]string{"App/Main.py": "a", "app/main.py": "b"})); err == nil || !strings.Contains(err.Error(), "duplicate") {
		t.Fatalf("expected case-insensitive duplicate rejection, got %v", err)
	}
	header := zip.FileHeader{Name: "app/link"}
	header.SetMode(os.ModeSymlink | 0o777)
	reader := &zip.Reader{File: []*zip.File{{FileHeader: header}}}
	if err := validateArchiveEntries(reader); err == nil || !strings.Contains(err.Error(), "unsupported") {
		t.Fatalf("expected symlink rejection, got %v", err)
	}
}

func TestValidateArchiveEntriesRejectsFileDirectoryCollisionAndLimits(t *testing.T) {
	if err := validateArchiveEntries(zipReader(t, map[string]string{"app": "file", "app/main.py": "child"})); err == nil || !strings.Contains(err.Error(), "file-directory collision") {
		t.Fatalf("expected file-directory collision rejection, got %v", err)
	}
	header := zip.FileHeader{Name: "large.bin", UncompressedSize64: 256*1024*1024 + 1}
	header.SetMode(0o600)
	reader := &zip.Reader{File: []*zip.File{{FileHeader: header}}}
	if err := validateArchiveEntries(reader); err == nil || !strings.Contains(err.Error(), "size limit") {
		t.Fatalf("expected member size rejection, got %v", err)
	}
}

func TestSafeExtractValidArchive(t *testing.T) {
	destination := t.TempDir()
	reader := zipReader(t, map[string]string{"app/main.py": "print('ok')", "requirements.txt": "x==1"})
	if err := safeExtract(reader, destination); err != nil {
		t.Fatal(err)
	}
	value, err := os.ReadFile(filepath.Join(destination, "app", "main.py"))
	if err != nil {
		t.Fatal(err)
	}
	if string(value) != "print('ok')" {
		t.Fatalf("unexpected extracted content %q", value)
	}
}
