from __future__ import annotations
import argparse, hashlib, importlib.util, subprocess, sys
from pathlib import Path

EXPECTED_BASE = {
    'app/services/extract_fidelity.py':'5051f1ee2dde767cc5ab1b2f884fba4e5fa0bf8c9d11d5e10a1eb836b260a44f',
    'app/services/qa_service.py':'eba31662dfb3e0fcded0673fdb4e949f2e419d8cddbbadff548d660254aee062',
    'app/services/repair_service.py':'084f682b3bf279bf13d27c85c33ba6d8c3a92854a7479d153a6e9e3a1689b97f',
    'app/static/app.js':'b84c7665be2e819cb12a83316d01b891a17e3b627aa3b7f995696375e00ccfb7',
}
EXPECTED_FINAL = {
    'app/services/extract_fidelity.py':'a5576f436874d9da6e460d96e2bdc1b80f0bec8dc9139f61b58fd7e8d543b73c',
    'app/services/qa_service.py':'c1d12ae55467c664e0a26459cba05535b5c866b01ac15e90886e9f51755dd10a',
    'app/services/repair_service.py':'a28023a8625f45a0f7cf014194255d12c5c3141d9b783977bcf23f70007f9533',
    'app/static/app.js':'2e4d2d2f554e0e48de23835cd9a56f2956e2f0a2123e501a9c104878abd19997',
}
EXPECTED_R13 = '60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991'
PARTS = ['R13_extract_fidelity.part01.py.txt','R13_extract_fidelity.part02.py.txt','R13_extract_fidelity.part03.py.txt']

OLD_HANDLER = '''$('#applyExtractPrint').addEventListener('click',()=>{\n  const regionButton=document.querySelector('[data-extract-mode="region"]');\n  const mode=regionButton?.classList.contains('active')?'region':'auto';\n  state.extractMode=mode;\n  const params={mode,x:number('#extractX',10),y:number('#extractY',10),width:number('#extractWidth',80),height:number('#extractHeight',80),sensitivity:number('#extractSensitivity',58),texture_reduction:number('#extractTexture',35),reduce_fabric_texture:number('#extractTexture',35)>0,feather:number('#extractFeather',1),crop_output:$('#extractCrop').checked,padding_mm:number('#extractPaddingMm',2),strict_roi:mode==='region'};\n  if ($('#extractPerspectiveEnabled').checked) params.perspective=pointValues('ep');\n  processSelected('extract_print',params,'Принт извлечён в отдельный PNG');\n});'''
NEW_HANDLER = '''$('#applyExtractPrint').addEventListener('click',()=>{\n  const regionButton=document.querySelector('[data-extract-mode="region"]');\n  const mode=regionButton?.classList.contains('active')?'region':'auto';\n  state.extractMode=mode;\n  const params={mode,x:number('#extractX',10),y:number('#extractY',10),width:number('#extractWidth',80),height:number('#extractHeight',80),strict_roi:mode==='region'};\n  if(mode==='auto') Object.assign(params,{sensitivity:number('#extractSensitivity',58),texture_reduction:number('#extractTexture',35),reduce_fabric_texture:number('#extractTexture',35)>0,feather:number('#extractFeather',1),crop_output:$('#extractCrop').checked,padding_mm:number('#extractPaddingMm',2)});\n  if ($('#extractPerspectiveEnabled').checked) params.perspective=pointValues('ep');\n  processSelected('extract_print',params,mode==='region'?'Рабочий фрагмент создан':'Принт извлечён в отдельный PNG');\n});'''

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fail(msg: str):
    raise RuntimeError(msg)

def load_patcher(review: Path):
    p=review/'R14_APPLY_TO_EXACT_R13.py'
    spec=importlib.util.spec_from_file_location('r14patcher',p)
    if not spec or not spec.loader: fail('PATCHER_IMPORT_FAILED')
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-root',type=Path,required=True)
    ap.add_argument('--review-root',type=Path,required=True)
    args=ap.parse_args()
    root=args.source_root.resolve(); review=args.review_root.resolve()
    if not root.is_dir(): fail(f'SOURCE_ROOT_MISSING:{root}')
    for rel,expected in EXPECTED_BASE.items():
        p=root/rel
        if not p.is_file(): fail(f'BASE_FILE_MISSING:{rel}')
        actual=sha(p)
        if actual!=expected: fail(f'BASE_SHA_MISMATCH:{rel}:expected={expected}:actual={actual}')
    r13=b''.join((review/n).read_bytes() for n in PARTS)
    if hashlib.sha256(r13).hexdigest()!=EXPECTED_R13: fail('EXACT_R13_RECONSTRUCTION_MISMATCH')
    candidate=load_patcher(review).patch_exact_r13(r13.decode('utf-8'),verify_hash=True).encode('utf-8')
    (root/'app/services/extract_fidelity.py').write_bytes(candidate)
    patch_file=review/'R14_QA_REPAIR_SEMANTIC_ROUTING.patch'
    proc=subprocess.run(['patch','-p1','--forward','--batch','-i',str(patch_file)],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if proc.returncode!=0: fail('QA_REPAIR_PATCH_FAILED:'+proc.stdout.strip())
    app=root/'app/static/app.js'; text=app.read_text('utf-8')
    if text.count(OLD_HANDLER)!=1: fail(f'CLIENT_HANDLER_BASE_COUNT:{text.count(OLD_HANDLER)}')
    app.write_text(text.replace(OLD_HANDLER,NEW_HANDLER,1),'utf-8',newline='\n')
    finals={rel:sha(root/rel) for rel in EXPECTED_FINAL}
    for rel,expected in EXPECTED_FINAL.items():
        if finals[rel]!=expected: fail(f'FINAL_SHA_MISMATCH:{rel}:expected={expected}:actual={finals[rel]}')
    print('R14_COMPOSITE_APPLY: PASS')
    for rel in sorted(finals): print(f'{rel} {finals[rel]}')
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print(f'R14_COMPOSITE_APPLY: BLOCKED: {exc}',file=sys.stderr); raise SystemExit(2)
