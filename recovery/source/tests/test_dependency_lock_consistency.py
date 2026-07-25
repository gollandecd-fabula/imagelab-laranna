from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRECT = {
    "fastapi",
    "starlette",
    "pydantic",
    "uvicorn",
    "click",
    "python-multipart",
    "pillow",
    "numpy",
    "opencv-python-headless",
}


def parse_pin(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)==([^\s;]+)\s*", value)
    assert match, f"dependency is not exactly pinned: {value}"
    return match.group(1).lower(), match.group(2)


def test_pyproject_direct_dependencies_match_requirements_lock() -> None:
    requirements: dict[str, str] = {}
    for raw in (ROOT / "requirements.txt").read_text("utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            name, version = parse_pin(line)
            requirements[name] = version

    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    metadata = dict(parse_pin(value) for value in project["dependencies"])

    assert set(metadata) == REQUIRED_DIRECT
    for name, version in metadata.items():
        assert requirements.get(name) == version, f"metadata/lock mismatch for {name}"
