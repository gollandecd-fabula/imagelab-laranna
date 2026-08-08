from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-SLU-M5-E2E"


def make_garment() -> bytes:
    image = Image.new("RGBA", (180, 220), (224, 228, 232, 255))
    draw = ImageDraw.Draw(image)
    draw.polygon([(45,35),(70,25),(82,45),(98,45),(110,25),(135,35),(166,70),(145,95),(135,82),(132,205),(48,205),(45,82),(35,95),(14,70)], fill=(30,34,42,255))
    draw.ellipse((67,72,116,125), fill=(224,65,38,255))
    draw.polygon([(55,135),(90,98),(124,135),(106,168),(72,168)], fill=(235,170,45,255))
    buffer=io.BytesIO(); image.save(buffer,"PNG",dpi=(300,300)); return buffer.getvalue()


def cleanup() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    (settings.project_dir / f"{PROJECT}.json").unlink(missing_ok=True)


def post_process(asset_id: str, operation: str, parameters: dict) -> dict:
    response=client.post(f"/api/projects/{PROJECT}/process",json={"asset_id":asset_id,"operation":operation,"parameters":parameters})
    assert response.status_code==200, f"{operation}: {response.text}"
    payload=response.json()
    assert payload["project"]["workspace"]["active_asset_id"]==payload["result"]["id"]
    assert payload["result"]["source_asset_id"]==asset_id
    assert payload["repair"]["attempt_count"]<=3
    return payload


def test_slu_m5_complete_non_destructive_pipeline() -> None:
    cleanup()
    upload=client.post(f"/api/projects/{PROJECT}/upload",files=[("files",("garment.png",make_garment(),"image/png"))])
    assert upload.status_code==200, upload.text
    source=upload.json()["uploaded"][0]

    extracted=post_process(source["id"],"extract_print",{
        "mode":"region","x":28,"y":25,"width":45,"height":58,"sensitivity":62,"texture_reduction":45,
        "crop_output":True,"padding_mm":2,"feather":1,"auto_repair":True,"ai_auto":True,
    })["result"]
    assert extracted["has_alpha"] is True

    improved=post_process(extracted["id"],"enhance",{
        "preset":"detail","width_mm":30,"height_mm":"","ppi":200,"preserve_aspect":True,
        "denoise":10,"auto_repair":True,"ai_auto":True,
    })["result"]
    assert abs(improved["print_width_mm"]-30)<0.2
    assert 199<=improved["ppi_x"]<=201

    selected=post_process(improved["id"],"select",{
        "mode":"element","brush_mm":3,"grow_mm":0,"feather":1,"ai_auto":False,
        "manual_edits":[{"tool":"rectangle","points":[[0.02,0.02],[0.98,0.98]]}],"auto_repair":True,
    })["result"]

    halftone=post_process(selected["id"],"halftone",{
        "mode":"mono","raster":"dot","shape":"circle","size_mm":0.22,"min_size_mm":0.08,"max_size_mm":0.42,
        "lpi":35,"angle":45,"density":68,"alpha_threshold":8,"auto_repair":True,"ai_auto":False,
    })["result"]
    assert halftone["parameters"]["physical_size_unit"]=="mm"

    vector=post_process(halftone["id"],"vectorize",{
        "mode":"mono","colors":2,"simplify_mm":0.18,"min_area_mm2":0.2,"auto_repair":True,"ai_auto":False,
    })["result"]
    assert vector["format"]=="SVG"

    exported=client.post(f"/api/projects/{PROJECT}/export",json={
        "asset_id":vector["id"],"format":"SVG","parameters":{"ppi":300,"ai_auto":False}
    })
    assert exported.status_code==200, exported.text
    export_payload=exported.json()
    assert export_payload["result"]["format"]=="SVG"
    assert export_payload["learning"]["module"]=="export"

    qa=client.get(f"/api/projects/{PROJECT}/qa?asset_id={export_payload['result']['id']}")
    assert qa.status_code==200, qa.text
    assert qa.json()["summary"]["quality_score"]>=85

    project=client.get(f"/api/projects/{PROJECT}").json()
    lineage={item["id"]:item.get("source_asset_id") for item in project["assets"]}
    cursor=export_payload["result"]["id"]
    seen=set()
    while lineage.get(cursor):
        assert cursor not in seen
        seen.add(cursor); cursor=lineage[cursor]
    assert cursor==source["id"]
    cleanup()
