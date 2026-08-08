from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from release_gate.finalize_unit_matrix import EXPECTED
from release_gate.run_unit_case import run_isolated

ROOT = Path(__file__).resolve().parents[1]


def test_timeout_reap_is_bounded_and_preserves_original_timeout() -> None:
    started = time.monotonic()
    code, _stdout, stderr, timed_out = run_isolated(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        dict(os.environ),
        timeout=1,
    )
    elapsed = time.monotonic() - started
    assert code == 124
    assert timed_out is True
    assert "TIMEOUT after 1s" in stderr
    assert elapsed < 8.0


def test_timeout_paths_have_no_unbounded_communicate_or_taskkill() -> None:
    unit = (ROOT / "release_gate" / "run_unit_case.py").read_text("utf-8")
    source = (ROOT / "release_gate" / "source_gate.py").read_text("utf-8")
    for text in (unit, source):
        assert "process.communicate()" not in text
        assert "taskkill" in text and "timeout=10" in text
        assert "process.kill()" in text
        assert "process.communicate(timeout=2)" in text


def test_isolated_processing_is_mandatory_in_all_manifests() -> None:
    assert EXPECTED["isolated-processing"] == "tests/test_isolated_processing.py"
    source_gate = (ROOT / "release_gate" / "source_gate.py").read_text("utf-8")
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-release.yml").read_text("utf-8")
    assert 'ROOT / "tests" / "test_isolated_processing.py"' in source_gate
    assert "id: isolated-processing" in workflow
    assert "file: tests/test_isolated_processing.py" in workflow
    assert len(EXPECTED) == 26
