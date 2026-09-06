from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'R7_REPRO_MANIFEST.json'
SNAPSHOT_PARTS = sorted(HERE.glob('R7_REPRO_SNAPSHOT.part*.b64'))
PATCH = HERE / 'R7_POST_CODEX_FIX.patch'
PYTEST = HERE / 'R7_REGRESSION_TESTS.py'
BROWSER = HERE / 'R7_BROWSER_REGRESSION.py'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_exact_files(root: Path, entries: list[dict], label: str, *, require_exact_set: bool = False) -> None:
    expected_paths = []
    for item in entries:
        rel = item['path']
        expected_paths.append(rel)
        path = root / rel
        if not path.is_file():
            raise AssertionError(f'{label} missing file: {rel}')
        data = path.read_bytes()
        got = sha256_bytes(data)
        if len(data) != item['size'] or got != item['sha256']:
            raise AssertionError(f'{label} mismatch {rel}: size={len(data)}/{item["size"]} sha={got}/{item["sha256"]}')
    if require_exact_set:
        actual = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
        if actual != sorted(expected_paths):
            raise AssertionError(f'{label} file-set mismatch: actual={actual} expected={sorted(expected_paths)}')


def safe_extract_tar_xz(raw: bytes, destination: Path) -> None:
    import io
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as tf:
        for member in tf.getmembers():
            if member.issym() or member.islnk() or member.isdev():
                raise AssertionError(f'unsafe archive member type: {member.name}')
            target = (destination / member.name).resolve()
            if destination.resolve() not in (target, *target.parents):
                raise AssertionError(f'archive traversal: {member.name}')
        try:
            tf.extractall(destination, filter='data')
        except TypeError:
            tf.extractall(destination)


def run(cmd: list[str], cwd: Path) -> None:
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='Self-contained R7 review reconstruction/regression runner')
    parser.add_argument('--keep-temp', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text('utf-8'))

    for item in manifest['support_files']:
        path = HERE / item['path']
        if not path.is_file():
            raise AssertionError(f'missing support file: {item["path"]}')
        data = path.read_bytes()
        if len(data) != item['size'] or sha256_bytes(data) != item['sha256']:
            raise AssertionError(f'support file mismatch: {item["path"]}')

    expected_parts = manifest['snapshot']['archive_parts']
    if [p.name for p in SNAPSHOT_PARTS] != expected_parts:
        raise AssertionError(f'snapshot part-set mismatch: {[p.name for p in SNAPSHOT_PARTS]} != {expected_parts}')
    encoded = ''.join(''.join(p.read_text('ascii').split()) for p in SNAPSHOT_PARTS)
    archive = base64.b64decode(encoded, validate=True)
    if len(archive) != manifest['snapshot']['archive_bytes']:
        raise AssertionError('snapshot archive size mismatch')
    if sha256_bytes(archive) != manifest['snapshot']['archive_sha256']:
        raise AssertionError('snapshot archive SHA mismatch')
    if sha256_bytes(PATCH.read_bytes()) != manifest['patch']['sha256']:
        raise AssertionError('patch SHA mismatch')

    temp = Path(tempfile.mkdtemp(prefix='imagelab-r7-repro-'))
    try:
        safe_extract_tar_xz(archive, temp)
        pre_root = temp / 'pre3'
        static_root = temp / 'finalstatic'
        verify_exact_files(pre_root, manifest['pre_endpoints'], 'pre endpoints', require_exact_set=True)
        verify_exact_files(static_root, manifest['final_static'], 'final static', require_exact_set=True)

        candidate = temp / 'candidate'
        shutil.copytree(pre_root, candidate)
        run(['git', 'apply', '--check', str(PATCH)], cwd=candidate)
        run(['git', 'apply', str(PATCH)], cwd=candidate)
        verify_exact_files(candidate, manifest['final_endpoints'], 'final endpoints', require_exact_set=True)

        changed = sorted(item['path'] for item in manifest['final_endpoints'])
        if changed != sorted(manifest['patch']['changed_paths']):
            raise AssertionError(f'changed path-set mismatch: {changed}')

        # Tie the exact patched JS endpoints to the exact final browser snapshot.
        for rel in ('app/static/app.js', 'app/static/m2a-ui-parts/13-m2a-closure-fixes.js.part'):
            if (candidate / rel).read_bytes() != (static_root / rel).read_bytes():
                raise AssertionError(f'browser snapshot endpoint mismatch: {rel}')

        run([sys.executable, str(PYTEST), '--candidate-root', str(candidate)], cwd=HERE)
        run([sys.executable, str(BROWSER), '--candidate-root', str(static_root)], cwd=HERE)

        print(json.dumps({
            'status': 'PASS',
            'pre_endpoint_files': len(manifest['pre_endpoints']),
            'final_endpoint_files': len(manifest['final_endpoints']),
            'final_static_files': len(manifest['final_static']),
            'changed_paths': changed,
            'snapshot_sha256': manifest['snapshot']['archive_sha256'],
            'evidence_ceiling': manifest['evidence_ceiling'],
        }, sort_keys=True))
        return 0
    finally:
        if args.keep_temp:
            print(f'KEPT_TEMP={temp}')
        else:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
