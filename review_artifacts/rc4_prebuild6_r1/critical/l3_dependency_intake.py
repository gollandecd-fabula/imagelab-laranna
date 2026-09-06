from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class WheelRequirement:
    import_name: str
    distribution: str
    version: str
    filename: str
    sha256: str


EXACT_L3_WHEELS: dict[str, WheelRequirement] = {
    "pillow_heif": WheelRequirement(import_name="pillow_heif", distribution="pillow-heif", version="1.6.0", filename="pillow_heif-1.6.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl", sha256="1629b5d5aaf484d5901297be024228abf8182c671e6c31dbbadf280faf1115c2"),
    "psd_tools": WheelRequirement(import_name="psd_tools", distribution="psd-tools", version="1.19.0", filename="psd_tools-1.19.0-cp313-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl", sha256="36e9057f6c1e8e1092b83b6974f221577d8df0e49455f50cebaeca61bcbb4c69"),
}
RECEIPT_NAME = "verified-runtime-receipt.json"
VERIFIED_WHEELS_DIR = ".verified_wheels"

def _canonical_name(value: str) -> str: return value.strip().lower().replace("_", "-").replace(".", "-")
def _sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""): digest.update(chunk)
    return digest.hexdigest()

def _safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members=[]; seen=set()
    for info in zf.infolist():
        name=info.filename.replace("\\","/"); parts=Path(name).parts; first=parts[0] if parts else ""; key=name.rstrip("/")
        if not key or name.startswith("/") or first.endswith(":") or ".." in parts or "\x00" in name: raise RuntimeError(f"unsafe wheel member path: {info.filename}")
        if key in seen: raise RuntimeError(f"duplicate wheel member path: {info.filename}")
        seen.add(key); mode=(info.external_attr>>16)&0o170000
        if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)): raise RuntimeError(f"unsupported wheel member type: {info.filename}")
        members.append(info)
    return members

def _read_wheel_metadata(path: Path) -> dict[str,str]:
    try:
        with zipfile.ZipFile(path) as zf:
            names=[n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
            if len(names)!=1: raise RuntimeError(f"wheel METADATA count must be 1: {path.name}")
            text=zf.read(names[0]).decode("utf-8",errors="strict")
    except (zipfile.BadZipFile,UnicodeDecodeError) as exc: raise RuntimeError(f"wheel METADATA unreadable: {path.name}") from exc
    msg=Parser().parsestr(text); return {"name":msg.get("Name",""),"version":msg.get("Version","")}

def _verify_wheel(path: Path, requirement: WheelRequirement) -> dict[str,str]:
    if path.name!=requirement.filename: raise RuntimeError(f"exact wheel filename mismatch: expected {requirement.filename}, got {path.name}")
    if not path.is_file(): raise RuntimeError(f"exact wheel missing: {path}")
    digest=_sha256(path)
    if digest!=requirement.sha256: raise RuntimeError(f"exact wheel SHA-256 mismatch for {path.name}: expected {requirement.sha256}, got {digest}")
    metadata=_read_wheel_metadata(path)
    if _canonical_name(metadata["name"])!=_canonical_name(requirement.distribution) or metadata["version"]!=requirement.version: raise RuntimeError(f"wheel METADATA mismatch for {path.name}: expected Name={requirement.distribution} Version={requirement.version}, got Name={metadata['name']} Version={metadata['version']}")
    return {"import_name":requirement.import_name,"distribution":requirement.distribution,"version":requirement.version,"filename":requirement.filename,"sha256":digest}

def compute_runtime_tree(runtime_dir: Path) -> dict[str,object]:
    runtime_dir=runtime_dir.resolve()
    if not runtime_dir.is_dir(): raise RuntimeError(f"verified runtime directory missing: {runtime_dir}")
    files=[p for p in runtime_dir.rglob("*") if p.is_file() and p.name!=RECEIPT_NAME and "__pycache__" not in p.parts and p.suffix not in {".pyc",".pyo"}]
    digest=hashlib.sha256()
    for path in sorted(files,key=lambda p:p.relative_to(runtime_dir).as_posix()):
        rel=path.relative_to(runtime_dir).as_posix().encode("utf-8"); digest.update(len(rel).to_bytes(4,"big")); digest.update(rel); digest.update(bytes.fromhex(_sha256(path)))
    return {"sha256":digest.hexdigest(),"file_count":len(files)}

def build_verified_runtime(*,wheel_dir:Path,runtime_dir:Path,requirements:Mapping[str,WheelRequirement]=EXACT_L3_WHEELS)->dict[str,object]:
    wheel_dir=wheel_dir.resolve(); runtime_dir=runtime_dir.resolve(); verified=[]
    for key in sorted(requirements):
        req=requirements[key]; wheel=wheel_dir/req.filename; verified.append((wheel,req,_verify_wheel(wheel,req)))
    if runtime_dir.exists(): shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True); verified_dir=runtime_dir/VERIFIED_WHEELS_DIR; verified_dir.mkdir(); receipts=[]
    for wheel,req,meta in verified:
        copied=verified_dir/wheel.name; shutil.copyfile(wheel,copied); _verify_wheel(copied,req)
        with zipfile.ZipFile(copied) as zf: zf.extractall(runtime_dir,members=_safe_members(zf))
        receipts.append(meta)
    tree=compute_runtime_tree(runtime_dir); receipt={"schema":"imagelab.verified-l3-runtime.v1","status":"PASS","runtime_tree":tree,"wheels":receipts}; (runtime_dir/RECEIPT_NAME).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),"utf-8"); return receipt

def validate_verified_runtime(*,runtime_dir:Path,requirements:Mapping[str,WheelRequirement]=EXACT_L3_WHEELS)->dict[str,object]:
    runtime_dir=runtime_dir.resolve(); receipt_path=runtime_dir/RECEIPT_NAME
    if not receipt_path.is_file(): raise RuntimeError(f"verified runtime receipt missing: {receipt_path}")
    try: receipt=json.loads(receipt_path.read_text("utf-8"))
    except Exception as exc: raise RuntimeError("verified runtime receipt unreadable") from exc
    if receipt.get("schema")!="imagelab.verified-l3-runtime.v1" or receipt.get("status")!="PASS": raise RuntimeError("verified runtime receipt schema/status invalid")
    verified_dir=runtime_dir/VERIFIED_WHEELS_DIR
    if not verified_dir.is_dir(): raise RuntimeError("verified runtime exact wheel store missing")
    expected_names={req.filename for req in requirements.values()}; actual_names={p.name for p in verified_dir.iterdir() if p.is_file()}
    if actual_names!=expected_names: raise RuntimeError(f"verified wheel set mismatch: expected={sorted(expected_names)}, actual={sorted(actual_names)}")
    wheel_receipts=[]
    for key in sorted(requirements): wheel_receipts.append(_verify_wheel(verified_dir/requirements[key].filename,requirements[key]))
    current_tree=compute_runtime_tree(runtime_dir)
    with tempfile.TemporaryDirectory(prefix="imagelab-runtime-rebuild-") as tmp:
        fresh_runtime=Path(tmp)/"runtime"; build_verified_runtime(wheel_dir=verified_dir,runtime_dir=fresh_runtime,requirements=requirements); expected_tree=compute_runtime_tree(fresh_runtime)
    if current_tree!=expected_tree: raise RuntimeError(f"verified runtime tree differs from freshly rebuilt pinned wheels: expected {expected_tree}, got {current_tree}")
    receipt_tree=receipt.get("runtime_tree") or {}
    if receipt_tree!=expected_tree: raise RuntimeError(f"verified runtime receipt tree does not match freshly rebuilt pinned wheels: expected {expected_tree}, got {receipt_tree}")
    return {"schema":receipt["schema"],"status":"PASS","runtime_tree":current_tree,"wheels":wheel_receipts}

def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--wheel-dir",type=Path,required=True); parser.add_argument("--runtime-dir",type=Path,required=True); parser.add_argument("--verify-only",action="store_true"); args=parser.parse_args()
    try: result=validate_verified_runtime(runtime_dir=args.runtime_dir) if args.verify_only else build_verified_runtime(wheel_dir=args.wheel_dir,runtime_dir=args.runtime_dir)
    except Exception as exc: print(json.dumps({"status":"BLOCKED","error":str(exc)},ensure_ascii=False,indent=2)); return 2
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
