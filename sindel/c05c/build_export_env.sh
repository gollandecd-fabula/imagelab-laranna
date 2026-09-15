#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${RUNNER_TEMP:-/tmp}/sindel-c05c-r3"
OUT="$ROOT/out/C05C_EXPORT_ENV_R3"
WHEEL="$OUT/wheelhouse"
RESOLVE="$WORK/resolve"
ENV_A="$WORK/envA"
ENV_B="$WORK/envB"
rm -rf "$WORK" "$OUT"
mkdir -p "$WHEEL"

python --version | tee "$OUT/BUILD_PYTHON.txt"
python -m venv "$RESOLVE"
"$RESOLVE/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"$RESOLVE/bin/python" -m pip install --disable-pip-version-check --no-input \
  --index-url https://download.pytorch.org/whl/cpu \
  'torch==2.10.0+cpu' 'torchaudio==2.10.0+cpu'
"$RESOLVE/bin/python" -m pip install --disable-pip-version-check --no-input 'executorch==1.1.0'
"$RESOLVE/bin/python" -m pip install --disable-pip-version-check --no-input -r "$ROOT/requirements.in"
"$RESOLVE/bin/python" -m pip freeze | LC_ALL=C sort > "$OUT/requirements.resolved.txt"

python -m pip wheel --disable-pip-version-check --no-input \
  --wheel-dir "$WHEEL" \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  -r "$OUT/requirements.resolved.txt"

for env in "$ENV_A" "$ENV_B"; do
  python -m venv "$env"
  "$env/bin/python" -m pip install --disable-pip-version-check --no-input \
    --no-index --find-links "$WHEEL" -r "$OUT/requirements.resolved.txt"
  "$env/bin/python" - <<'PY'
import json, sys, torch, torchaudio, executorch
from executorch.exir import to_edge_transform_and_lower, EdgeCompileConfig
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
import transformers, diffusers, safetensors, omegaconf, conformer, einops
assert torch.__version__ == '2.10.0+cpu', torch.__version__
assert torchaudio.__version__ == '2.10.0+cpu', torchaudio.__version__
import importlib.metadata as md
assert md.version('executorch') == '1.1.0'
print(json.dumps({'python':sys.version,'torch':torch.__version__,'torchaudio':torchaudio.__version__,'executorch':md.version('executorch'),'transformers':transformers.__version__}, sort_keys=True))
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
python - "$OUT" <<'PY'
import hashlib,json,pathlib,sys
out=pathlib.Path(sys.argv[1])
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
 return h.hexdigest()
wheels=[]
for p in sorted((out/'wheelhouse').iterdir(), key=lambda x:x.name.lower()):
 if p.is_file(): wheels.append({'name':p.name,'size':p.stat().st_size,'sha256':sha(p)})
lock={'schema':'sindel.cp034.c05c.export-env.r3','python':'3.11.15','torch':'2.10.0+cpu','torchaudio':'2.10.0+cpu','executorch':'1.1.0','android_runtime_target':'executorch-android-1.1.0','offline_rebuilds':2,'offline_rebuild_freeze_equal':True,'wheel_count':len(wheels),'wheels':wheels,'freeze':(out/'requirements.offline.freeze.txt').read_text().splitlines()}
(out/'C05C_EXPORT_ENV_LOCK_R3.json').write_text(json.dumps(lock,indent=2),encoding='utf-8')
PY
python - "$OUT" <<'PY'
import hashlib,pathlib,sys
out=pathlib.Path(sys.argv[1]); bad=[]
for line in (out/'SHA256SUMS.txt').read_text().splitlines():
 h,rel=line.split(None,1); p=out/rel.strip(); got=hashlib.sha256(p.read_bytes()).hexdigest()
 if h!=got: bad.append((rel,h,got))
if bad: raise SystemExit(bad)
print('C05C_EXPORT_ENV_R3_PASS')
PY
