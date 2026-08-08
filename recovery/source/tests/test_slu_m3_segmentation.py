from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from app.ai.runtime import get_ai_engine


def _scene(kind: str) -> tuple[Image.Image, np.ndarray]:
    width, height = 256, 220
    fabric=(70,85,105); background=(225,230,235)
    image=Image.new('RGB',(width,height),background); draw=ImageDraw.Draw(image)
    box=(35,22,220,202); draw.rounded_rectangle(box,radius=24,fill=fabric)
    truth=Image.new('1',(width,height)); truth_draw=ImageDraw.Draw(truth)
    if kind in {'patterned','patterned_print'}:
        for x in range(box[0],box[2],10):
            draw.line((x,box[1],x,box[3]),fill=tuple(min(255,v+22) for v in fabric),width=3)
    if kind != 'patterned':
        center=(128,116); ellipse=(90,84,166,148); bar=(118,68,138,164)
        truth_draw.ellipse(ellipse,fill=1); truth_draw.rectangle(bar,fill=1)
        color=tuple(v+18 for v in fabric) if kind=='low_contrast' else (235,65,25)
        draw.ellipse(ellipse,fill=color); draw.rectangle(bar,fill=color)
    return image.convert('RGBA'), np.asarray(truth,dtype=bool)


def _iou(mask: np.ndarray, truth: np.ndarray) -> float:
    actual=mask>16; union=np.logical_or(actual,truth).sum()
    return float(np.logical_and(actual,truth).sum()/max(1,union))


def test_low_contrast_print_is_recovered() -> None:
    image, truth=_scene('low_contrast')
    mask,_=get_ai_engine().segment_print(image,feather=0,module='slu_regression_low_contrast')
    assert _iou(mask,truth)>=0.95


def test_patterned_fabric_without_print_is_rejected() -> None:
    image, truth=_scene('patterned')
    mask,_=get_ai_engine().segment_print(image,feather=0,module='slu_regression_patterned')
    assert not truth.any()
    assert float((mask>16).mean())<=0.01


def test_print_on_patterned_fabric_does_not_include_stripes() -> None:
    image, truth=_scene('patterned_print')
    mask,_=get_ai_engine().segment_print(image,feather=0,module='slu_regression_patterned_print')
    assert _iou(mask,truth)>=0.95
