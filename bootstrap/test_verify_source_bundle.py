from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


ROOT = Path(__file__).resolve().parent.parent
VERIFIER = ROOT / "bootstrap" / "verify_source_bundle.py"
VERSION = "1.4.3-redteam-cycle6-candidate"
BUILD_ID = "RT8-M6-20260724-02"
REQUIRED_CONTENT = {
    "app/main.py": "print('imagelab')\n",
    "app/config.py": f"VERSION = {VERSION!r}\nBUILD_ID = {BUILD_ID!r}\n",
    "release_gate/source_gate.py": "print('gate')\n",
    "release_gate/run_clean_install_gate.ps1": "exit 0\n",
    "scripts/build_zero_trust_candidate.py": "print('build')\n",
    "windows_installer/installer/main.go": "package main\nfunc main() {}\n",
    "requirements.txt": "\n",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in entries.items():
            bundle.writestr(name, content)


def run_verifier(
    directory: Path,
    *,
    entries: dict[str, str],
    expected_sha256: str | None = None,
    pinned_sha256: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object], Path]:
    archive = directory / "imagelab-source.zip"
    checksum = directory / "imagelab-source.sha256"
    evidence = directory / "evidence.json"
    extract_to = directory / "source-tree"
    write_zip(archive, entries)
    actual = sha256(archive)
    expected = expected_sha256 or actual
    pinned = pinned_sha256 or expected
    checksum.write_text(f"{pinned}  {archive.name}\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--archive",
            str(archive),
            "--checksum",
            str(checksum),
            "--output",
            str(evidence),
            "--extract-to",
            str(extract_to),
            "--expected-sha256",
            expected,
            "--expected-version",
            VERSION,
            "--expected-build-id",
            BUILD_ID,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    return completed, payload, extract_to


class SourceBundleVerifierTests(unittest.TestCase):
    def test_valid_exact_bundle_is_published_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed, payload, extract_to = run_verifier(
                Path(temporary), entries=dict(REQUIRED_CONTENT)
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["failures"], [])
            self.assertEqual(payload["extract_state"], "PUBLISHED_ATOMICALLY")
            self.assertTrue((extract_to / "app/config.py").is_file())

    def test_hash_mismatch_reports_only_primary_admission_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed, payload, extract_to = run_verifier(
                Path(temporary),
                entries=dict(REQUIRED_CONTENT),
                expected_sha256="0" * 64,
                pinned_sha256="0" * 64,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(payload["failures"], ["SOURCE_EXACT_SHA256_MISMATCH"])
            self.assertEqual(payload["extract_state"], "BLOCKED_BY_ARCHIVE_ADMISSION")
            self.assertNotIn("missing_required_files", payload)
            self.assertFalse(extract_to.exists())

    def test_traversal_member_is_rejected_without_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            entries = dict(REQUIRED_CONTENT)
            entries["../escape.txt"] = "blocked"
            completed, payload, extract_to = run_verifier(directory, entries=entries)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("SOURCE_ZIP_UNSAFE_MEMBER", payload["failures"])
            self.assertFalse((directory.parent / "escape.txt").exists())
            self.assertFalse(extract_to.exists())

    def test_private_runtime_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entries = dict(REQUIRED_CONTENT)
            entries["data/private.json"] = "{}"
            completed, payload, extract_to = run_verifier(
                Path(temporary), entries=entries
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn(
                "SOURCE_BUNDLE_PRIVACY_DENYLIST_VIOLATION",
                payload["failures"],
            )
            self.assertFalse(extract_to.exists())

    def test_duplicate_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / "imagelab-source.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(archive, "w") as bundle:
                    for name, content in REQUIRED_CONTENT.items():
                        bundle.writestr(name, content)
                    bundle.writestr("app/main.py", "duplicate")
            actual = sha256(archive)
            checksum = directory / "imagelab-source.sha256"
            checksum.write_text(f"{actual}  {archive.name}\n", encoding="utf-8")
            evidence = directory / "evidence.json"
            extract_to = directory / "source-tree"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER),
                    "--archive",
                    str(archive),
                    "--checksum",
                    str(checksum),
                    "--output",
                    str(evidence),
                    "--extract-to",
                    str(extract_to),
                    "--expected-sha256",
                    actual,
                    "--expected-version",
                    VERSION,
                    "--expected-build-id",
                    BUILD_ID,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 1)
            self.assertIn("SOURCE_ZIP_DUPLICATE_MEMBER", payload["failures"])
            self.assertFalse(extract_to.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
