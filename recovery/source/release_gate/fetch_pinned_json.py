from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=1024 * 1024)
    args = parser.parse_args()

    expected = args.sha256.strip().lower()
    if not valid_sha256(expected):
        raise SystemExit("invalid expected SHA-256")
    if args.max_bytes <= 0 or args.max_bytes > 16 * 1024 * 1024:
        raise SystemExit("invalid max-bytes")

    parsed = urllib.parse.urlparse(args.url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise SystemExit("only credential-free HTTPS URLs are allowed")

    request = urllib.request.Request(
        args.url,
        headers={"User-Agent": "ImageLab-Zero-Trust-Evidence-Fetch/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme.lower() != "https" or not final.netloc:
                raise RuntimeError("redirected evidence URL is not HTTPS")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > args.max_bytes:
                raise RuntimeError("evidence exceeds configured size limit")
            payload = response.read(args.max_bytes + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"failed to download evidence: {exc}") from exc

    if len(payload) > args.max_bytes:
        raise SystemExit("evidence exceeds configured size limit")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise SystemExit("evidence SHA-256 mismatch")
    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"evidence is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise SystemExit("evidence top level must be a JSON object")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=output.name + ".", suffix=".tmp", dir=output.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, output)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    print(
        json.dumps(
            {"status": "PASS", "sha256": actual, "output": output.as_posix()}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
