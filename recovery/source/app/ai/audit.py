from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


MAX_AUDIT_FILE_BYTES = 20 * 1024 * 1024
GENESIS_HASH = "0" * 64


class _AuditFileLock(AbstractContextManager["_AuditFileLock"]):
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "_AuditFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        self._fd = fd
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
            os.fsync(fd)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    self._fd = None
                    raise RuntimeError("Не удалось получить блокировку AI-аудита") from exc
                time.sleep(0.025)

    def __exit__(self, exc_type, exc, traceback) -> None:
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[depth-limit]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if key == "features":
                if isinstance(nested, list):
                    result["feature_count"] = len(nested)
                continue
            result[str(key)[:80]] = _sanitize(nested, depth + 1)
        return result
    if isinstance(value, list):
        return [_sanitize(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, float):
        return value if math.isfinite(value) else "[non-finite]"
    if value is None or isinstance(value, (bool, int)):
        return value
    return str(value)[:500]


def _record_hash(item: dict[str, Any]) -> str:
    canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class AIAuditStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or settings.ai_audit_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._process_lock_path = self.directory / ".ai-audit.lock"

    def _current_path(self, day: str) -> Path:
        base = self.directory / f"ai-audit-{day}.jsonl"
        if not base.exists() or base.stat().st_size < MAX_AUDIT_FILE_BYTES:
            return base
        index = 1
        while True:
            candidate = self.directory / f"ai-audit-{day}-{index:03d}.jsonl"
            if not candidate.exists() or candidate.stat().st_size < MAX_AUDIT_FILE_BYTES:
                return candidate
            index += 1

    @staticmethod
    def _previous_hash(path: Path) -> str:
        if not path.exists() or path.stat().st_size == 0:
            return GENESIS_HASH
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                position = stream.tell() - 1
                while position >= 0:
                    stream.seek(position)
                    if stream.read(1) not in {b"\n", b"\r"}:
                        break
                    position -= 1
                end = position + 1
                while position >= 0:
                    stream.seek(position)
                    if stream.read(1) == b"\n":
                        break
                    position -= 1
                stream.seek(position + 1)
                line = stream.read(end - position - 1).decode("utf-8")
            item = json.loads(line)
            value = item.get("record_hash") if isinstance(item, dict) else None
            return value if isinstance(value, str) and len(value) == 64 else "legacy-unverified"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return "corrupt-unverified"

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        day = created_at[:10]
        with self._lock, _AuditFileLock(self._process_lock_path):
            path = self._current_path(day)
            item = {
                "id": uuid.uuid4().hex,
                "created_at": created_at,
                "previous_hash": self._previous_hash(path),
                **_sanitize(record),
            }
            item["record_hash"] = _record_hash(item)
            encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        return item

    def verify_file(self, path: Path) -> dict[str, Any]:
        valid = True
        checked = 0
        previous = GENESIS_HASH
        legacy_seen = False
        try:
            lines = path.read_text("utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            return {"path": path.name, "valid": False, "checked": 0, "error": str(exc)}
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                return {"path": path.name, "valid": False, "checked": checked, "line": number, "error": "invalid_json"}
            if not isinstance(item, dict) or "record_hash" not in item:
                legacy_seen = True
                previous = "legacy-unverified"
                continue
            stored = item.get("record_hash")
            content = dict(item)
            content.pop("record_hash", None)
            if stored != _record_hash(content):
                valid = False
                return {"path": path.name, "valid": False, "checked": checked, "line": number, "error": "record_hash_mismatch"}
            expected_previous = previous
            if item.get("previous_hash") != expected_previous:
                valid = False
                return {"path": path.name, "valid": False, "checked": checked, "line": number, "error": "chain_mismatch"}
            previous = str(stored)
            checked += 1
        return {"path": path.name, "valid": valid, "checked": checked, "legacy_seen": legacy_seen, "last_hash": previous}

    def verify_all(self) -> list[dict[str, Any]]:
        with self._lock, _AuditFileLock(self._process_lock_path):
            return [self.verify_file(path) for path in sorted(self.directory.glob("ai-audit-*.jsonl"))]

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100_000))
        items: list[dict[str, Any]] = []
        with self._lock, _AuditFileLock(self._process_lock_path):
            paths = sorted(self.directory.glob("ai-audit-*.jsonl"), reverse=True)
            for path in paths:
                try:
                    lines = path.read_text("utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for line in reversed(lines):
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        items.append(item)
                    if len(items) >= limit:
                        return items
        return items
