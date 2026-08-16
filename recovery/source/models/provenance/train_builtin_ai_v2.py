# SPDX-License-Identifier: MIT-0
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np

SEED = 20260817
VERSION = "2.0.0"
MODEL_IDS = (
    "pixel_subject", "pixel_print", "content_classifier", "quality_risk",
    "restoration_profile", "tiny_restorer", "halftone_recommender",
    "vector_recommender", "export_recommender", "size_assistant", "qa_anomaly",
)


def canonical_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", "utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60.0, 60.0)))


def train_binary(x: np.ndarray, y: np.ndarray, *, iterations: int = 900, lr: float = 0.08, l2: float = 0.002) -> dict:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    w = np.zeros(z.shape[1], dtype=np.float64)
    b = 0.0
    pos = max(float((y > 0.5).sum()), 1.0)
    neg = max(float((y <= 0.5).sum()), 1.0)
    sw = np.where(y > 0.5, len(y) / (2 * pos), len(y) / (2 * neg))
    for _ in range(iterations):
        p = sigmoid(z @ w + b)
        err = (p - y) * sw
        w -= lr * ((z.T @ err) / len(y) + l2 * w)
        b -= lr * float(err.mean())
    pred = sigmoid(z @ w + b) >= 0.5
    acc = float((pred == (y >= 0.5)).mean())
    return {"kind":"binary_logistic","mean":mean.tolist(),"scale":scale.tolist(),"coef":w.tolist(),"intercept":float(b)}, acc


def train_softmax(x: np.ndarray, labels: np.ndarray, classes: list[str], *, iterations: int = 1200, lr: float = 0.07, l2: float = 0.002) -> tuple[dict, float]:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    k = len(classes)
    w = np.zeros((k, z.shape[1]), dtype=np.float64)
    b = np.zeros(k, dtype=np.float64)
    onehot = np.eye(k, dtype=np.float64)[y]
    for _ in range(iterations):
        logits = z @ w.T + b
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(np.clip(logits, -60.0, 60.0))
        p = e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)
        err = (p - onehot) / len(y)
        w -= lr * (err.T @ z + l2 * w)
        b -= lr * err.sum(axis=0)
    logits = z @ w.T + b
    acc = float((np.argmax(logits, axis=1) == y).mean())
    return {"kind":"softmax","classes":classes,"mean":mean.tolist(),"scale":scale.tolist(),"coef":w.tolist(),"intercept":b.tolist()}, acc


def train_regression(x: np.ndarray, y: np.ndarray, outputs: list[str], ridge: float = 1e-3) -> tuple[dict, float]:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    a = np.c_[z, np.ones(len(z))]
    reg = np.eye(a.shape[1]) * ridge
    reg[-1,-1] = 0.0
    beta = np.linalg.solve(a.T @ a + reg, a.T @ y)
    coef = beta[:-1].T
    intercept = beta[-1]
    pred = a @ beta
    mae = float(np.mean(np.abs(pred - y)))
    return {"kind":"linear_regression","outputs":outputs,"mean":mean.tolist(),"scale":scale.tolist(),"coef":coef.tolist(),"intercept":intercept.tolist()}, mae


def _scene(rng: np.random.Generator, w: int, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w]
    bg0 = rng.integers(185, 246, size=3).astype(np.float32)
    bg1 = rng.integers(175, 241, size=3).astype(np.float32)
    t = (yy / max(h-1,1))[...,None]
    rgb = np.clip(bg0*(1-t)+bg1*t + rng.normal(0, 1.3, (h,w,1)), 0, 255).astype(np.uint8)
    subject = np.zeros((h,w), np.uint8)
    cx = int(w * rng.uniform(0.47,0.53)); top=int(h*rng.uniform(0.10,0.16)); bottom=int(h*rng.uniform(0.86,0.93))
    half_top=int(w*rng.uniform(0.20,0.25)); half_bottom=int(w*rng.uniform(0.28,0.34))
    pts=np.array([
        [cx-half_top,top],[cx-int(half_top*.45),top-int(h*.03)],[cx-int(half_top*.18),top+int(h*.07)],
        [cx+int(half_top*.18),top+int(h*.07)],[cx+int(half_top*.45),top-int(h*.03)],[cx+half_top,top],
        [cx+int(w*.39),int(h*.28)],[cx+int(w*.30),int(h*.42)],[cx+half_bottom,int(h*.36)],
        [cx+half_bottom,bottom],[cx-half_bottom,bottom],[cx-half_bottom,int(h*.36)],
        [cx-int(w*.30),int(h*.42)],[cx-int(w*.39),int(h*.28)]],np.int32)
    cv2.fillPoly(subject,[pts],255)
    cv2.ellipse(subject,(cx,top+int(h*.06)),(int(w*.075),int(h*.055)),0,0,360,0,-1)
    fabric=rng.integers(25,120,size=3).astype(np.float32)
    shade=(0.88+0.10*np.sin(xx/rng.uniform(14,30))+0.06*np.cos(yy/rng.uniform(18,36)))[...,None]
    weave=(rng.normal(0,2.0,(h,w,1))+2*np.sin(xx/rng.uniform(2.5,5.5))[...,None])
    shirt=np.clip(fabric*shade+weave,0,255).astype(np.uint8)
    rgb[subject>0]=shirt[subject>0]
    pr=np.zeros_like(subject)
    pcx=cx+int(rng.uniform(-.04,.04)*w); pcy=int(h*rng.uniform(.48,.59)); sx=int(w*rng.uniform(.12,.20)); sy=int(h*rng.uniform(.10,.17))
    if rng.random()<0.5:
        cv2.ellipse(pr,(pcx,pcy),(sx,sy),rng.uniform(-15,15),0,360,255,-1)
        cv2.rectangle(pr,(pcx-int(sx*.45),pcy),(pcx+int(sx*.45),pcy+int(sy*1.4)),255,-1)
    else:
        poly=np.array([[pcx,pcy-sy],[pcx+sx,pcy],[pcx+int(sx*.45),pcy+sy],[pcx-int(sx*.6),pcy+int(sy*.8)],[pcx-sx,pcy]],np.int32)
        cv2.fillPoly(pr,[poly],255)
    pr=cv2.bitwise_and(pr,subject)
    # Choose print colors deliberately separated from the fabric.
    base=np.array([int(v) for v in fabric])
    candidates=[np.array([235,75,35]),np.array([240,185,35]),np.array([30,180,210]),np.array([235,235,230]),np.array([20,20,25])]
    color=max(candidates,key=lambda c: float(np.linalg.norm(c-base)))
    alt=np.clip(color.astype(int)+rng.integers(-25,26,size=3),0,255).astype(np.uint8)
    sel=pr>0
    pattern=((xx+yy)//max(2,int(rng.integers(3,8))))%2
    rgb[sel]=np.where(pattern[sel,None]==0,color,alt)
    return rgb, subject, pr


def image_features(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    rgb=np.asarray(rgb,dtype=np.uint8); h,w=rgb.shape[:2]
    if alpha is None: alpha=np.full((h,w),255,np.uint8)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV); gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    lap=cv2.Laplacian(gray,cv2.CV_32F); edges=cv2.Canny(gray,60,150)
    hist=cv2.calcHist([gray],[0],None,[32],[0,256]).ravel().astype(np.float64); hist/=max(hist.sum(),1)
    nz=hist[hist>0]; entropy=float(-(nz*np.log2(nz)).sum())/5.0
    border=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]],axis=0).astype(np.float32)
    center=rgb[h//4:3*h//4,w//4:3*w//4].reshape(-1,3).astype(np.float32)
    block=gray.astype(np.float32); blockiness=0.0
    if w>=16 and h>=16:
        right,left=block[:,8::8],block[:,7:-1:8]; bottom,top=block[8::8,:],block[7:-1:8,:]
        v=np.abs(right-left).mean() if right.size and left.shape==right.shape else 0.0
        q=np.abs(bottom-top).mean() if bottom.size and top.shape==bottom.shape else 0.0
        blockiness=(v+q)/510.0
    return np.asarray([
        *(rgb.mean(axis=(0,1))/255.0),*(rgb.std(axis=(0,1))/128.0),
        hsv[:,:,1].mean()/255.0,hsv[:,:,1].std()/128.0,gray.mean()/255.0,gray.std()/128.0,
        min(float(lap.var())/5000.0,4.0),float((edges>0).mean()),float((alpha>16).mean()),
        float(border.std())/128.0,float(np.linalg.norm(center.mean(axis=0)-border.mean(axis=0)))/441.7,
        entropy,blockiness,math.log(max(w/max(h,1),1e-4)),min(math.log2(max(w,1))/16.0,1.0),min(math.log2(max(h,1))/16.0,1.0)
    ],dtype=np.float32)


def pixel_features(rgb: np.ndarray) -> np.ndarray:
    rgb=np.asarray(rgb,dtype=np.uint8); h,w=rgb.shape[:2]; rgbf=rgb.astype(np.float32)/255.0
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV).astype(np.float32); hsv[:,:,0]/=180.0; hsv[:,:,1:]/=255.0
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(np.float32)/255.0; gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)/255.0
    mu=cv2.GaussianBlur(gray,(0,0),2.0); sq=cv2.GaussianBlur(gray*gray,(0,0),2.0); sd=np.sqrt(np.clip(sq-mu*mu,0,None))
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3); gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3); edge=np.sqrt(gx*gx+gy*gy)
    yy,xx=np.mgrid[0:h,0:w].astype(np.float32); xx/=max(w-1,1); yy/=max(h-1,1)
    bd=np.minimum.reduce([xx,yy,1-xx,1-yy]); frame=np.concatenate([rgbf[0],rgbf[-1],rgbf[:,0],rgbf[:,-1]],axis=0); med=np.median(frame,axis=0)
    cbd=np.linalg.norm(rgbf-med[None,None,:],axis=2)/math.sqrt(3)
    f=np.dstack([rgbf,hsv,lab,mu,sd,np.clip(edge,0,2),xx,yy,bd,cbd]); return f.reshape(-1,f.shape[2]).astype(np.float32)


def qa_features(rgb: np.ndarray, alpha: np.ndarray, operation: str) -> np.ndarray:
    one=np.zeros(4,np.float32); one[{"background":0,"extract_print":1,"halftone":2,"vectorize":3}.get(operation,3)]=1
    a=np.asarray(alpha,np.uint8); coverage=float((a>16).mean()); arr=a.astype(np.int16); edges=np.zeros_like(a,dtype=bool)
    if a.shape[1]>1:
        x=np.abs(arr[:,1:]-arr[:,:-1])>=20; edges[:,1:]|=x; edges[:,:-1]|=x
    if a.shape[0]>1:
        y=np.abs(arr[1:,:]-arr[:-1,:])>=20; edges[1:,:]|=y; edges[:-1,:]|=y
    return np.concatenate([image_features(rgb,a),one,[coverage,float(edges.mean())]]).astype(np.float32)


def build_datasets(rng: np.random.Generator):
    px=[]; ys=[]; yp=[]; img=[]; content=[]; qx=[]; qlabels={k:[] for k in ("blur","noise","low_contrast","compression")}; rest_x=[]; rest_y=[]
    rec_x=[]; half_y=[]; vec_y=[]; exp_y=[]; size_y=[]; qa_x=[]; qa_y=[]
    class_names=["garment","product","print"]
    rest_classes=["clean","deblur","denoise","contrast","compression"]
    for i in range(150):
        w=int(rng.integers(128,193)); h=int(rng.integers(150,241))
        rgb,sub,pr=_scene(rng,w,h); alpha=np.full((h,w),255,np.uint8)
        pf=pixel_features(rgb); sf=(sub.reshape(-1)>0); ppf=(pr.reshape(-1)>0)
        # balanced per-scene sampling for pixel classifiers
        for label_arr,target in ((sf,ys),(ppf,yp)):
            pos=np.flatnonzero(label_arr); neg=np.flatnonzero(~label_arr)
            n=min(180,len(pos),len(neg))
            idx=np.r_[rng.choice(pos,n,replace=False),rng.choice(neg,n,replace=False)]
            if target is ys:
                px.append(pf[idx]); ys.extend(label_arr[idx].astype(int).tolist())
            else:
                # pixel_print features need their own sampled rows
                # append to separate tuple later through a parallel list
                pass
        # print training independent rows
        pos=np.flatnonzero(ppf); neg=np.flatnonzero(~ppf); n=min(180,len(pos),len(neg)); idx=np.r_[rng.choice(pos,n,replace=False),rng.choice(neg,n,replace=False)]
        # store print rows in object pair
        if i==0: print_px=[]
        print_px.append(pf[idx]); yp.extend(ppf[idx].astype(int).tolist())
        basef=image_features(rgb,alpha); img.append(basef); content.append(0)
        # product: clean central object on flat background
        prod=np.full_like(rgb,rng.integers(205,245,size=3,dtype=np.uint8)); x0=int(w*.22); x1=int(w*.78); y0=int(h*.18); y1=int(h*.82); prod[y0:y1,x0:x1]=rng.integers(35,190,size=3,dtype=np.uint8)
        img.append(image_features(prod,alpha)); content.append(1)
        # standalone print graphic
        standalone=np.full_like(rgb,245); cv2.circle(standalone,(w//2,h//2),min(w,h)//4,(230,70,30),-1); cv2.line(standalone,(w//4,h//2),(3*w//4,h//2),(25,30,40),max(2,w//30))
        img.append(image_features(standalone,alpha)); content.append(2)
        variants=[("clean",rgb),
                  ("deblur",cv2.GaussianBlur(rgb,(0,0),1.8)),
                  ("denoise",np.clip(rgb.astype(np.float32)+rng.normal(0,18,rgb.shape),0,255).astype(np.uint8)),
                  ("contrast",np.clip((rgb.astype(np.float32)-128)*0.35+128,0,255).astype(np.uint8))]
        ok,enc=cv2.imencode('.jpg',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR),[int(cv2.IMWRITE_JPEG_QUALITY),28]); comp=cv2.cvtColor(cv2.imdecode(enc,cv2.IMREAD_COLOR),cv2.COLOR_BGR2RGB) if ok else rgb.copy(); variants.append(("compression",comp))
        for name,v in variants:
            f=image_features(v,alpha); rest_x.append(f); rest_y.append(rest_classes.index(name)); qx.append(f)
            for k in qlabels: qlabels[k].append(1 if k==({"deblur":"blur","denoise":"noise","contrast":"low_contrast","compression":"compression"}.get(name)) else 0)
        # recommendations from deterministic scene properties
        f=basef; rec_x.append(f)
        edge=f[11]; entropy=f[15]; sat=f[6]
        half_y.append(0 if edge<0.045 else (1 if edge>0.10 else 2))
        vec_y.append([float(np.clip(round(3+10*sat+5*edge),2,16)), float(np.clip(6.0-30*edge+1.5*entropy,0.5,8.0))])
        exp_y.append(2 if edge>0.09 and entropy<0.75 else (0 if sat>0.42 else 1))
        # synthetic safe margins tied to garment bbox
        ys0,xs0=np.where(sub>0); left=float(xs0.min()/w); top=float(ys0.min()/h); right=float(1-xs0.max()/w); bottom=float(1-ys0.max()/h)
        size_y.append([left*100,top*100,right*100,bottom*100])
        for op in ("background","extract_print","halftone","vectorize"):
            good=qa_features(rgb,sub if op!="extract_print" else pr,op); qa_x.append(good); qa_y.append(0)
            bad=good.copy(); bad[-2]=0.995 if op in ("extract_print","halftone") else 0.002; bad[-1]=0.0; qa_x.append(bad); qa_y.append(1)
    return {
        "subject_x":np.vstack(px),"subject_y":np.asarray(ys),"print_x":np.vstack(print_px),"print_y":np.asarray(yp),
        "content_x":np.vstack(img),"content_y":np.asarray(content),"quality_x":np.vstack(qx),"quality_labels":{k:np.asarray(v) for k,v in qlabels.items()},
        "rest_x":np.vstack(rest_x),"rest_y":np.asarray(rest_y),"rec_x":np.vstack(rec_x),"half_y":np.asarray(half_y),"vec_y":np.asarray(vec_y),"exp_y":np.asarray(exp_y),"size_y":np.asarray(size_y),
        "qa_x":np.vstack(qa_x),"qa_y":np.asarray(qa_y),
    }


def train_tiny_restorer(rng: np.random.Generator) -> tuple[dict,float]:
    rows=[]; targets=[]
    for _ in range(70):
        h=w=48
        yy,xx=np.mgrid[0:h,0:w]
        clean=np.zeros((h,w,3),np.float32)
        for c in range(3):
            clean[:,:,c]=np.clip(rng.uniform(.15,.85)+.18*np.sin(xx/rng.uniform(5,13)+rng.uniform(0,6.28))+.14*np.cos(yy/rng.uniform(6,15)+rng.uniform(0,6.28)),0,1)
        clean_u8=(clean*255).astype(np.uint8)
        corrupt=cv2.GaussianBlur(clean_u8,(0,0),rng.uniform(.7,1.5)).astype(np.float32)/255.0
        corrupt=np.clip(corrupt+rng.normal(0,.018,corrupt.shape),0,1)
        pad=np.pad(corrupt,((1,1),(1,1),(0,0)),mode='reflect')
        patches=[]
        for dy in range(3):
            for dx in range(3): patches.append(pad[dy:dy+h,dx:dx+w,:])
        a=np.stack(patches,axis=2).reshape(-1,27)
        b=clean.reshape(-1,3)
        idx=rng.choice(len(a),min(700,len(a)),replace=False); rows.append(a[idx]); targets.append(b[idx])
    x=np.vstack(rows).astype(np.float64); y=np.vstack(targets).astype(np.float64)
    a=np.c_[x,np.ones(len(x))]; ridge=np.eye(28)*1e-3; ridge[-1,-1]=0
    beta=np.linalg.solve(a.T@a+ridge,a.T@y)
    coef=np.zeros((3,3,3,3),np.float64)
    for outc in range(3): coef[outc]=beta[:-1,outc].reshape(3,3,3)
    intercept=beta[-1].tolist(); pred=a@beta; mse=float(np.mean((pred-y)**2))
    return {"id":"tiny_restorer","version":VERSION,"kind":"conv3x3_linear","coef":coef.tolist(),"intercept":intercept,"training_mse":mse},mse


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--out",required=True); args=ap.parse_args()
    out=Path(args.out).resolve()
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    rng=np.random.default_rng(SEED)
    ds=build_datasets(rng); metrics={}
    models={}
    p,metrics['pixel_subject_train_accuracy']=train_binary(ds['subject_x'],ds['subject_y']); p.update(id='pixel_subject',version=VERSION,feature_count=ds['subject_x'].shape[1]); models['pixel_subject']=p
    p,metrics['pixel_print_train_accuracy']=train_binary(ds['print_x'],ds['print_y']); p.update(id='pixel_print',version=VERSION,feature_count=ds['print_x'].shape[1]); models['pixel_print']=p
    p,metrics['content_train_accuracy']=train_softmax(ds['content_x'],ds['content_y'],['garment','product','print']); p.update(id='content_classifier',version=VERSION); models['content_classifier']=p
    quality={"id":"quality_risk","version":VERSION,"kind":"multi_binary","models":{}}
    for k,y in ds['quality_labels'].items():
        q,acc=train_binary(ds['quality_x'],y); quality['models'][k]=q; metrics[f'quality_{k}_accuracy']=acc
    models['quality_risk']=quality
    p,metrics['restoration_profile_train_accuracy']=train_softmax(ds['rest_x'],ds['rest_y'],['clean','deblur','denoise','contrast','compression']); p.update(id='restoration_profile',version=VERSION); models['restoration_profile']=p
    p,metrics['halftone_train_accuracy']=train_softmax(ds['rec_x'],ds['half_y'],['dot','line','hybrid']); p.update(id='halftone_recommender',version=VERSION); models['halftone_recommender']=p
    p,metrics['vector_train_mae']=train_regression(ds['rec_x'],ds['vec_y'],['colors','simplify']); p.update(id='vector_recommender',version=VERSION); models['vector_recommender']=p
    p,metrics['export_train_accuracy']=train_softmax(ds['rec_x'],ds['exp_y'],['dtf_png','marketplace_webp','vector_svg']); p.update(id='export_recommender',version=VERSION); models['export_recommender']=p
    p,metrics['size_train_mae']=train_regression(ds['rec_x'],ds['size_y'],['left','top','right','bottom']); p.update(id='size_assistant',version=VERSION); models['size_assistant']=p
    p,metrics['qa_anomaly_train_accuracy']=train_binary(ds['qa_x'],ds['qa_y']); p.update(id='qa_anomaly',version=VERSION,operation_count=4); models['qa_anomaly']=p
    p,metrics['tiny_restorer_training_mse']=train_tiny_restorer(rng); models['tiny_restorer']=p
    filenames={mid:f"{mid}_v2.json" for mid in MODEL_IDS}
    for mid in MODEL_IDS: canonical_write(out/filenames[mid],models[mid])
    specs=[]
    tasks={'pixel_subject':'segmentation','pixel_print':'segmentation','content_classifier':'classification','quality_risk':'quality','restoration_profile':'recommendation','tiny_restorer':'restoration','halftone_recommender':'recommendation','vector_recommender':'recommendation','export_recommender':'recommendation','size_assistant':'recommendation','qa_anomaly':'qa'}
    for mid in MODEL_IDS:
        f=out/filenames[mid]; specs.append({'id':mid,'version':VERSION,'task':tasks[mid],'filename':f.name,'sha256':sha256(f),'runtime':'numpy-linear-ml'})
    manifest={'schema':1,'suite':'ImageLab Built-in AI','version':VERSION,'training_seed':SEED,'training_generator':'provenance/train_builtin_ai_v2.py','training_data':'deterministic procedural synthetic feature/image scenes only; no external datasets or pretrained weights','models':specs,'metrics':{k:round(float(v),9) for k,v in metrics.items()},'limitations':['Compact non-neural local models trained only on deterministic synthetic scenes.','Synthetic metrics do not prove equivalent accuracy on arbitrary real photographs.','No runtime auto-download or cloud inference.']}
    canonical_write(out/'manifest.json',manifest)
    print(json.dumps({'status':'PASS','out':str(out),'metrics':manifest['metrics'],'model_count':len(specs)},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
