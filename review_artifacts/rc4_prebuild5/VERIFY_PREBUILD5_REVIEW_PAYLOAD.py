from __future__ import annotations
import base64, hashlib, io, json, lzma, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
TARGET_TREE='95b7c2d2bfd104500d794ada51940aaccbd7e8e3494d51abf3ac14d5fb2bdb9e'
def h(b): return hashlib.sha256(b).hexdigest()
def main():
 idx=json.loads((ROOT/'PREBUILD5_TEXT_BUNDLE_INDEX_XZ.json').read_text('utf-8'))
 binary=json.loads((ROOT/'PREBUILD5_BINARY_OBJECTS.json').read_text('utf-8'))
 parts=[]
 for row in idx['chunks']:
  b=(ROOT/'source_bundle_chunks'/row['name']).read_bytes()
  if h(b)!=row['sha256'] or len(b)!=row['chars']: raise SystemExit('chunk mismatch '+row['name'])
  parts.append(b)
 xz=base64.b64decode(b''.join(parts),validate=True)
 if h(xz)!=idx['tar_xz_sha256'] or len(xz)!=idx['tar_xz_bytes']: raise SystemExit('archive mismatch')
 tar=lzma.decompress(xz)
 entries={}
 with tarfile.open(fileobj=io.BytesIO(tar),mode='r:') as tf:
  for m in tf.getmembers():
   if not m.isfile() or m.name in entries: raise SystemExit('unsafe/duplicate tar member')
   f=tf.extractfile(m); data=f.read() if f else b''; entries[m.name]=h(data)
 if len(entries)!=idx['utf8_file_count']: raise SystemExit('text count mismatch')
 for row in binary['objects']:
  if row['path'] in entries: raise SystemExit('binary/text overlap')
  entries[row['path']]=row['sha256']
 digest=hashlib.sha256()
 for rel in sorted(entries):
  b=rel.encode('utf-8'); digest.update(len(b).to_bytes(4,'big')); digest.update(b); digest.update(bytes.fromhex(entries[rel]))
 if len(entries)!=215 or digest.hexdigest()!=TARGET_TREE: raise SystemExit(f'tree mismatch {len(entries)} {digest.hexdigest()}')
 print('PASS',len(entries),digest.hexdigest())
if __name__=='__main__': main()
