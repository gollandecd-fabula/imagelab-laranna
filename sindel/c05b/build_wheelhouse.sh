#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${RUNNER_TEMP:-/tmp}/sindel-c05b-r3"
OUT="$ROOT/out/C05B_WHEELHOUSE_R3"
WHEEL="$OUT/wheelhouse"
RESOLVE="$WORK/resolve"
ENV_A="$WORK/envA"
ENV_B="$WORK/envB"
CHATTERBOX="$WORK/chatterbox"
PERTH_COMMIT="ff1c8ac55a976971245cdd53c18d6131ca00d993"
CHATTERBOX_COMMIT="5de7a54aa4e5e2baadb0182dde554908b48b85c2"
CHATTERBOX_VERSION="0.1.7"
UV_VERSION="0.10.0"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$WHEEL"

python --version | tee "$OUT/BUILD_PYTHON.txt"
python -m pip install --disable-pip-version-check --no-input "uv==$UV_VERSION"
uv --version | tee "$OUT/UV_VERSION.txt"

uv venv --python "$(command -v python)" --seed "$RESOLVE"
uv pip install --python "$RESOLVE/bin/python" \
  --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.6.0+cpu" "torchaudio==2.6.0+cpu"
uv pip install --python "$RESOLVE/bin/python" -r "$ROOT/requirements.in"

"$RESOLVE/bin/python" -m pip freeze | LC_ALL=C sort > "$OUT/requirements.resolved.txt"

python -m pip wheel --disable-pip-version-check --no-input \
  --wheel-dir "$WHEEL" \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  -r "$OUT/requirements.resolved.txt"

PERTH_VERSION="$($RESOLVE/bin/python - <<'PY'
import importlib.metadata
print(importlib.metadata.version('resemble-perth'))
PY
)"
export PERTH_VERSION CHATTERBOX_VERSION
python - "$OUT/requirements.resolved.txt" "$OUT/requirements.offline.txt" <<'PY'
import os, sys
src, dst = sys.argv[1:]
perth_version = os.environ['PERTH_VERSION']
chatterbox_version = os.environ['CHATTERBOX_VERSION']
lines=[]
for line in open(src, encoding='utf-8'):
    s=line.strip()
    if s.lower().startswith('resemble-perth @ git+'):
        lines.append(f'resemble-perth=={perth_version}\n')
    else:
        lines.append(line)
lines.append(f'chatterbox-tts=={chatterbox_version}\n')
open(dst,'w',encoding='utf-8').writelines(lines)
PY

git clone --quiet https://github.com/resemble-ai/chatterbox.git "$CHATTERBOX"
git -C "$CHATTERBOX" checkout --quiet "$CHATTERBOX_COMMIT"
ACTUAL_CHATTERBOX="$(git -C "$CHATTERBOX" rev-parse HEAD)"
test "$ACTUAL_CHATTERBOX" = "$CHATTERBOX_COMMIT"
printf '%s\n' "$ACTUAL_CHATTERBOX" > "$OUT/CHATTERBOX_COMMIT.txt"
printf '%s\n' "$PERTH_COMMIT" > "$OUT/PERTH_COMMIT.txt"

# Build the exact frozen Chatterbox source itself into the wheelhouse so the
# offline environments contain real package metadata and never rely on PYTHONPATH.
python -m pip wheel --disable-pip-version-check --no-input --no-deps \
  --wheel-dir "$WHEEL" "$CHATTERBOX"
ls "$WHEEL"/chatterbox_tts-${CHATTERBOX_VERSION}-*.whl > "$OUT/CHATTERBOX_WHEEL.txt"

for env in "$ENV_A" "$ENV_B"; do
  python -m venv "$env"
  "$env/bin/python" -m pip install --disable-pip-version-check --no-input \
    --no-index --find-links "$WHEEL" -r "$OUT/requirements.offline.txt"
  "$env/bin/python" - <<'PY'
import hashlib, importlib, importlib.metadata, json, pathlib, platform, sys
mods=['numpy','torch','torchaudio','librosa','omegaconf','safetensors','transformers','tokenizers','perth','conformer','spacy_pkuseg','pykakasi','diffusers','s3tokenizer']
rows={}
for m in mods:
    obj=importlib.import_module(m)
    rows[m]=getattr(obj,'__version__', None)
import chatterbox
import chatterbox.mtl_tts
import chatterbox.models.t3.t3
import chatterbox.models.tokenizers.tokenizer
import chatterbox.models.s3gen.flow_matching
rows['chatterbox-tts']=importlib.metadata.version('chatterbox-tts')
rows['python']=sys.version
rows['platform']=platform.platform()

def git_blob_sha(path):
    data=pathlib.Path(path).read_bytes()
    return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
expected={
 'mtl_tts.py':'ec5ebff418f6abf283127c4de6bbe99580f29e69',
 'models/t3/t3.py':'d83de261e249648f6654e2bac7cb10390af983c9',
 'models/tokenizers/tokenizer.py':'84d45d35d2db9c6c576a4af98a7ab91a704af9f2',
 'models/s3gen/flow_matching.py':'6a9635bb0c12ad19f4511632333a4b4856bff031',
}
base=pathlib.Path(chatterbox.__file__).parent
source={}
for rel,want in expected.items():
    got=git_blob_sha(base/rel)
    source[rel]={'expected':want,'actual':got,'equal':got==want}
    if got!=want:
        raise SystemExit(f'frozen source drift {rel}: {got} != {want}')
rows['frozen_source_blobs']=source
print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
PY
done > "$OUT/OFFLINE_IMPORT_PROBE.txt"

"$ENV_A/bin/python" -m pip freeze | LC_ALL=C sort > "$OUT/envA.freeze.txt"
"$ENV_B/bin/python" -m pip freeze | LC_ALL=C sort > "$OUT/envB.freeze.txt"
cmp -s "$OUT/envA.freeze.txt" "$OUT/envB.freeze.txt"
cp "$OUT/envA.freeze.txt" "$OUT/requirements.offline.freeze.txt"

(
  cd "$OUT"
  find wheelhouse -maxdepth 1 -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS.txt
)

python - "$OUT" "$ROOT/requirements.in" <<'PY'
import hashlib, json, pathlib, sys
out=pathlib.Path(sys.argv[1]); req=pathlib.Path(sys.argv[2])
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()
wheels=[]
for p in sorted((out/'wheelhouse').iterdir(), key=lambda x:x.name.lower()):
    if p.is_file(): wheels.append({'name':p.name,'size':p.stat().st_size,'sha256':sha(p)})
freeze=(out/'requirements.offline.freeze.txt').read_text(encoding='utf-8').splitlines()
lock={
  'schema':'sindel.cp034.c05b.dependency-lock.r3',
  'python_line':'CPython 3.11.15',
  'torch':'2.6.0+cpu',
  'torchaudio':'2.6.0+cpu',
  'uv':'0.10.0',
  'chatterbox_commit':'5de7a54aa4e5e2baadb0182dde554908b48b85c2',
  'chatterbox_version':'0.1.7',
  'perth_commit':'ff1c8ac55a976971245cdd53c18d6131ca00d993',
  'direct_requirements':req.read_text(encoding='utf-8').splitlines(),
  'resolved_freeze':freeze,
  'wheel_count':len(wheels),
  'wheels':wheels,
  'offline_rebuilds':2,
  'offline_rebuild_freeze_equal':True,
  'import_probe':'PASS',
  'frozen_chatterbox_source_blob_gate':'PASS'
}
(out/'C05B_DEPENDENCY_LOCK.json').write_text(json.dumps(lock,indent=2,ensure_ascii=False),encoding='utf-8')
sbom={'schema':'sindel.cp034.c05b.sbom.r3','packages':[]}
for line in freeze:
    if '==' in line:
        n,v=line.split('==',1); sbom['packages'].append({'name':n,'version':v})
(out/'C05B_SBOM.json').write_text(json.dumps(sbom,indent=2,ensure_ascii=False),encoding='utf-8')
manifest={p.name:{'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(out.iterdir()) if p.is_file()}
(out/'ARTIFACT_MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
PY

python - "$OUT" <<'PY'
import hashlib, pathlib, sys
out=pathlib.Path(sys.argv[1]); bad=[]
for line in (out/'SHA256SUMS.txt').read_text().splitlines():
    h, rel=line.split(None,1); p=out/rel.strip()
    got=hashlib.sha256(p.read_bytes()).hexdigest()
    if got!=h: bad.append((str(p),h,got))
if bad: raise SystemExit(f'SHA mismatch: {bad}')
print('C05B_WHEELHOUSE_R3_PASS')
PY
