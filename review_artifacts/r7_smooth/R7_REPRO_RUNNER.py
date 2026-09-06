from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'R7_REPRO_MANIFEST.json'
ARCHIVE_PARTS = sorted(HERE.glob('R7_BASE_APP.part*.b64'))
PATCH = HERE / 'R7_POST_CODEX_FIX.patch'
PYTEST = HERE / 'R7_REGRESSION_TESTS.py'
BROWSER = HERE / 'R7_BROWSER_REGRESSION.py'
FIXTURES = HERE / 'R7_FIXTURES.json'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text('utf-8'))


def file_map(root: Path, entries: list[dict]) -> dict[str, tuple[int, str]]:
    result = {}
    for item in entries:
        path = root / item['path']
        if not path.is_file():
            raise AssertionError(f'missing file: {item["path"]}')
        data = path.read_bytes()
        result[item['path']] = (len(data), sha256_bytes(data))
    actual = sorted('app/' + p.relative_to(root / 'app').as_posix() for p in (root / 'app').rglob('*') if p.is_file())
    expected = sorted(item['path'] for item in entries)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise AssertionError(f'app file-set mismatch missing={missing} extra={extra}')
    return result


def verify_entries(root: Path, entries: list[dict], label: str) -> None:
    actual = file_map(root, entries)
    for item in entries:
        got_size, got_sha = actual[item['path']]
        if got_size != item['size'] or got_sha != item['sha256']:
            raise AssertionError(
                f'{label} mismatch {item["path"]}: size {got_size}/{item["size"]} sha {got_sha}/{item["sha256"]}'
            )


def safe_extract_tar_gz(raw: bytes, destination: Path) -> None:
    import io
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tf:
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


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='Self-contained R7 review reconstruction/regression runner')
    parser.add_argument('--keep-temp', action='store_true')
    args = parser.parse_args()

    manifest = load_manifest()
    for item in manifest.get('support_files', []):
        path = HERE / item['path']
        if not path.is_file():
            raise AssertionError(f'missing support file: {item["path"]}')
        data = path.read_bytes()
        if len(data) != item['size'] or sha256_bytes(data) != item['sha256']:
            raise AssertionError(f'support file mismatch: {item["path"]}')
    expected_parts = manifest['base_app']['archive_parts']
    if [p.name for p in ARCHIVE_PARTS] != expected_parts:
        raise AssertionError(f'archive part-set mismatch: {[p.name for p in ARCHIVE_PARTS]} != {expected_parts}')
    encoded = ''.join(''.join(path.read_text('ascii').split()) for path in ARCHIVE_PARTS)
    archive = base64.b64decode(encoded, validate=True)
    if sha256_bytes(archive) != manifest['base_app']['archive_sha256']:
        raise AssertionError('base app archive SHA mismatch')
    if len(archive) != manifest['base_app']['archive_bytes']:
        raise AssertionError('base app archive size mismatch')
    if sha256_bytes(PATCH.read_bytes()) != manifest['patch']['sha256']:
        raise AssertionError('patch SHA mismatch')

    fixtures = json.loads(FIXTURES.read_text('utf-8'))
    for key in ('source', 'result'):
        data = base64.b64decode(fixtures[key]['base64'], validate=True)
        if sha256_bytes(data) != fixtures[key]['sha256']:
            raise AssertionError(f'fixture SHA mismatch: {key}')

    temp = Path(tempfile.mkdtemp(prefix='imagelab-r7-repro-'))
    try:
        candidate = temp / 'candidate'
        candidate.mkdir()
        safe_extract_tar_gz(archive, candidate)
        verify_entries(candidate, manifest['base_app']['files'], 'base')

        run(['git', 'apply', '--check', str(PATCH)], cwd=candidate)
        run(['git', 'apply', str(PATCH)], cwd=candidate)
        verify_entries(candidate, manifest['final_app']['files'], 'final')

        base_index = {e['path']: e['sha256'] for e in manifest['base_app']['files']}
        final_index = {e['path']: e['sha256'] for e in manifest['final_app']['files']}
        changed = sorted(path for path in base_index if base_index[path] != final_index[path])
        if changed != sorted(manifest['patch']['changed_paths']):
            raise AssertionError(f'changed-path mismatch: {changed}')

        env = dict(os.environ)
        env['PYTHONPATH'] = str(candidate)
        run([sys.executable, str(PYTEST), '--candidate-root', str(candidate)], cwd=HERE, env=env)
        run([sys.executable, str(BROWSER), '--candidate-root', str(candidate), '--fixtures', str(FIXTURES)], cwd=HERE, env=env)

        print(json.dumps({
            'status': 'PASS',
            'base_files': len(manifest['base_app']['files']),
            'final_files': len(manifest['final_app']['files']),
            'changed_paths': changed,
            'final_tree_sha256': manifest['final_app']['tree_sha256'],
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
