from __future__ import annotations

import importlib.util
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERIFIER_PATH = ROOT / "bootstrap" / "verify_source_bundle.py"
SPEC = importlib.util.spec_from_file_location("imagelab_bootstrap_verifier", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _member(name: str, mode: int) -> zipfile.ZipInfo:
    member = zipfile.ZipInfo(name)
    member.create_system = 3
    member.external_attr = mode << 16
    return member


def test_permission_bits_without_file_type_are_safe() -> None:
    member = _member("app/main.py", 0o600)
    assert VERIFIER.member_mode(member) == 0o600
    assert not VERIFIER.is_unsafe_member(member)


def test_explicit_regular_file_is_safe() -> None:
    member = _member("app/main.py", stat.S_IFREG | 0o600)
    assert not VERIFIER.is_unsafe_member(member)


def test_explicit_symlink_and_device_are_blocked() -> None:
    assert VERIFIER.is_unsafe_member(_member("app/link", stat.S_IFLNK | 0o777))
    assert VERIFIER.is_unsafe_member(_member("app/device", stat.S_IFCHR | 0o600))
