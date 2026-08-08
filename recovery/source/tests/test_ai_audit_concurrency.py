from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

from app.ai.audit import AIAuditStore, GENESIS_HASH


def _append_worker(directory: str, worker: int, count: int, start) -> None:
    store = AIAuditStore(Path(directory))
    start.wait(10)
    for index in range(count):
        store.append({"worker": worker, "index": index, "features": [1.0, 2.0]})


def test_ai_audit_multiprocess_chain_has_no_lost_records(tmp_path: Path) -> None:
    context = mp.get_context("spawn")
    start = context.Event()
    workers = [
        context.Process(target=_append_worker, args=(str(tmp_path), worker, 20, start))
        for worker in range(3)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0

    store = AIAuditStore(tmp_path)
    records = store.recent(1000)
    assert len(records) == 60
    verdicts = store.verify_all()
    assert len(verdicts) == 1
    assert verdicts[0]["valid"] is True
    assert verdicts[0]["checked"] == 60


def test_ai_audit_chain_detects_tampering(tmp_path: Path) -> None:
    store = AIAuditStore(tmp_path)
    first = store.append({"event": "first"})
    second = store.append({"event": "second"})
    assert first["previous_hash"] == GENESIS_HASH
    assert second["previous_hash"] == first["record_hash"]

    path = next(tmp_path.glob("ai-audit-*.jsonl"))
    text = path.read_text("utf-8")
    path.write_text(text.replace('"event":"first"', '"event":"forged"'), "utf-8")
    verdict = store.verify_file(path)
    assert verdict["valid"] is False
    assert verdict["error"] == "record_hash_mismatch"
