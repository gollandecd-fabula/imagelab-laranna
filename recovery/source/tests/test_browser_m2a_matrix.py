from __future__ import annotations

import io
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
from PIL import Image

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = Path(os.environ.get("M2A_ARTIFACT_DIR", ROOT / "artifacts/m2a-visual"))


def _png(color: tuple[int, int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(stream, format="PNG")
    return stream.getvalue()


def _asset(asset_id: str, name: str, color: str) -> dict:
    return {"id":asset_id,"original_name":name,"stored_name":f"{asset_id}.png","preview_name":f"{asset_id}.png","size_bytes":1024,"sha256":color*64,"mime_type":"image/png","format":"PNG","width_px":640,"height_px":480,"ppi_x":300,"ppi_y":300,"ppi_origin":"embedded","print_width_mm":54.19,"print_height_mm":40.64,"color_mode":"RGB","color_profile":"sRGB","has_alpha":False,"created_at":"2026-07-27T00:00:00Z","preview_url":f"/preview/{asset_id}.png","checks":[],"source_asset_id":None,"operation":None,"parameters":{},"ai":{},"download_url":f"/api/assets/{asset_id}/file"}


def _document() -> str:
    html=(ROOT/"app/static/index.html").read_text("utf-8")
    css="\n".join((ROOT/f"app/static/{name}").read_text("utf-8") for name in ("styles.css","m1-hardening.css","m2a-ui.css","m2a-completeness.css"))
    m2a="".join(path.read_text("utf-8") for path in sorted((ROOT/"app/static/m2a-ui-parts").glob("*.js.part")))
    js="\n".join(((ROOT/"app/static/app.js").read_text("utf-8"),(ROOT/"app/static/m1-hardening.js").read_text("utf-8"),m2a)).replace("</script","<\\/script")
    return html.replace("<head>",'<head><base href="http://imagelab.test/">',1).replace('<link rel="stylesheet" href="/static/styles.css?v=1.4.9-recovery-candidate">',f"<style>{css}</style>").replace('<script src="/static/app.js?v=1.4.9-recovery-candidate"></script>',f"<script>{js}</script>")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as manager:
        executable=next((path for path in (shutil.which("chromium"),shutil.which("chromium-browser"),shutil.which("google-chrome")) if path),None)
        instance=manager.chromium.launch(headless=True,executable_path=executable) if executable else manager.chromium.launch(headless=True)
        try: yield instance
        finally: instance.close()


def _load(page):
    assets=[_asset("aaaaaaaa","one.png","a"),_asset("bbbbbbbb","two.png","b"),_asset("cccccccc","three.png","c")]
    project={"id":"TS-001","title":"M2A Matrix","created_at":"x","updated_at":"x","assets":assets,"workspace":{"active_asset_id":"aaaaaaaa","active_revision":1,"presets":{}}}
    images={"aaaaaaaa":_png((220,70,70)),"bbbbbbbb":_png((50,100,220)),"cccccccc":_png((40,180,100))};process_calls=[]
    def handler(route):
        request=route.request;path=urlparse(request.url).path
        if path=="/api/projects": body=[project]
        elif path=="/api/projects/TS-001" and request.method=="GET": body=project
        elif path=="/api/projects/TS-001/active": project["workspace"]["active_asset_id"]=request.post_data_json["asset_id"];project["workspace"]["active_revision"]+=1;body=project
        elif path.startswith("/api/m2a/projects/TS-001/workspace/") and request.method=="PUT": section=path.rsplit("/",1)[-1];project["workspace"][section]=request.post_data_json["value"];body={"project":project,"section":section,"status":"saved"}
        elif path=="/api/m2a/projects/TS-001/presets" and request.method=="PUT": payload=request.post_data_json;project["workspace"].setdefault("presets",{})[payload["name"]]={"module":payload["module"],"parameters":payload["parameters"]};body={"project":project,"status":"saved"}
        elif path=="/api/m2a/diagnostics": body={"application":{"host_policy":"localhost_only"},"system":{"cpu_logical":8,"gpu":"not_configured"},"runtime":{"status":"ready","providers":["local"],"models":[]},"disk":{"free_bytes":1000000},"privacy":{"image_content_included":False,"secrets_included":False}}
        elif path=="/api/health": body={"status":"ok","version":"m2a","build_id":"M2A","install_id":"browser","scope":"M2A","host_policy":"localhost_only"}
        elif path=="/api/ai/health": body={"status":"ready","runtime":"local","models":[]}
        elif path=="/api/projects/TS-001/process" and request.method=="POST":
            time.sleep(.06);payload=request.post_data_json;process_calls.append(payload["asset_id"]);source=next(asset for asset in project["assets"] if asset["id"]==payload["asset_id"]);result=dict(source);result["id"]=f"result{len(process_calls):02d}";result["original_name"]=f"result-{len(process_calls)}.png";result["source_asset_id"]=source["id"];result["operation"]=payload["operation"];result["sha256"]=str(len(process_calls))*64;result["preview_url"]=f"/preview/{source['id']}.png";project["assets"].append(result);project["workspace"]["active_asset_id"]=result["id"];body={"project":project,"result":result,"source_asset_id":source["id"],"attempts":[result]}
        elif path.startswith("/preview/"): key=Path(path).stem;route.fulfill(status=200,content_type="image/png",body=images.get(key,images["aaaaaaaa"]));return
        else: body={"project":project,"result":project["assets"][-1],"results":[],"overall_passed":True,"checks":[]}
        route.fulfill(status=200,content_type="application/json",body=json.dumps(body))
    page.route("**/*",handler);page.set_content(_document(),wait_until="load");expect(page.locator("#projectName")).to_have_text("M2A Matrix");return project,process_calls


def _alpha_sum(page)->int:
    return int(page.locator("canvas.m2a-selection-layer").evaluate("canvas => {const d=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;let s=0;for(let i=3;i<d.length;i+=4)s+=d[i];return s;}"))


def test_m2a_visual_matrix_navigation_and_scope_lock(browser)->None:
    ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
    for width in (800,1024,1280,1440,1920):
        page=browser.new_page(viewport={"width":width,"height":900});_load(page)
        if width<=1023: page.locator(".m2a-mobile-nav").select_option("geometry")
        else: page.locator('[data-module="geometry"]').click()
        expect(page.locator('[data-pane="geometry"]')).to_have_class("module-pane active");assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth")<=1;page.screenshot(path=str(ARTIFACT_DIR/f"m2a-{width}.png"),full_page=True);page.close()
    page=browser.new_page(viewport={"width":1280,"height":900});_load(page);assert page.locator(".nav-svg").count()==page.locator(".nav-item").count()
    for module in ("projects","presets","batch","background","color","palette","dtf","masters","logo","cardlab","settings"): page.locator(f'[data-module="{module}"]').click();expect(page.locator(f'[data-pane="{module}"]')).to_have_class("module-pane m2a-pane active")
    for action in ("m2aApplyBackground","m2aApplyColor","m2aDtfQa","m2aDtfMaster","m2aCardMaster","m2aPrepareLogo"): expect(page.locator(f"#{action}")).to_be_disabled()
    expect(page.locator("#m2aDtfStatus")).to_contain_text("BLOCKED");page.locator("#m2aPreparePrint").click();expect(page.locator("#m2aAutopilotDialog")).to_have_class("m2a-autopilot-dialog open");expect(page.locator("#m2aMandatoryQa")).to_be_checked();expect(page.locator("#m2aMandatoryQa")).to_be_disabled();expect(page.locator("#m2aAutoStart")).to_be_disabled();page.close()


def test_m2a_size_preview_mask_and_workspace_persistence(browser)->None:
    page=browser.new_page(viewport={"width":1280,"height":900});project,_=_load(page);page.locator('[data-module="geometry"]').click();chain=page.locator('[data-size-grid="geometrySizeGrid"] .m2a-chain');expect(chain).to_have_attribute("aria-pressed","true");page.locator("#widthMm").fill("100");expect(page.locator("#heightMm")).to_have_value("75.00");chain.click();expect(chain).to_have_attribute("aria-pressed","false");prior_height=page.locator("#heightMm").input_value();page.locator("#widthMm").fill("120");expect(page.locator("#heightMm")).to_have_value(prior_height)
    page.locator('[data-preview-mode="difference"]').click();expect(page.locator('[data-preview-mode="difference"]')).to_have_class("m2a-tool active");page.locator("#m2aOneToOne").click();expect(page.locator("#m2aZoomValue")).to_have_text("100%");page.locator("#m2aFit").click();assert page.locator("#m2aZoomValue").inner_text().endswith("%");assert page.locator("#m2aZoomValue").inner_text()!="Fit"
    before_assets=len(project["assets"]);page.locator('[data-preview-only="geometry"]').click();expect(page.locator(".m2a-preview-note").first).to_contain_text("новая версия не создана");assert len(project["assets"])==before_assets
    page.locator("#usePerspective").check();expect(page.locator(".m2a-perspective-handle")).to_have_count(4);handle=page.locator(".m2a-perspective-handle").first;box=handle.bounding_box();assert box;page.mouse.move(box["x"]+5,box["y"]+5);page.mouse.down();page.mouse.move(box["x"]+25,box["y"]+20);page.mouse.up();assert float(page.locator("#pTLx").input_value())>0
    page.locator('[data-module="selection"]').click();page.locator('[data-mask-tool="add"]').click();canvas=page.locator("canvas.m2a-selection-layer");expect(canvas).to_be_visible();cbox=canvas.bounding_box();assert cbox;page.mouse.move(cbox["x"]+cbox["width"]*.2,cbox["y"]+cbox["height"]*.2);page.mouse.down();page.mouse.move(cbox["x"]+cbox["width"]*.45,cbox["y"]+cbox["height"]*.45,steps=6);page.mouse.up();expect.poll(lambda:bool(project["workspace"].get("masks",{}).get("aaaaaaaa"))).to_be_truthy();assert _alpha_sum(page)>0;page.locator('#historyStrip [data-asset-id="bbbbbbbb"]').click();expect.poll(lambda:page.evaluate("state.selectedId")).to_equal("bbbbbbbb");assert _alpha_sum(page)==0;page.locator('#historyStrip [data-asset-id="aaaaaaaa"]').click();expect.poll(lambda:page.evaluate("state.selectedId")).to_equal("aaaaaaaa");assert _alpha_sum(page)>0
    page.locator('[data-module="settings"]').click();page.locator("#m2aDefaultFolder").fill("D:\\ImageLab\\Projects");page.locator('[data-model-pack="restore"]').check();page.locator("#m2aSaveSettings").click();expect.poll(lambda:project["workspace"].get("settings",{}).get("default_folder")).to_equal("D:\\ImageLab\\Projects");expect(page.locator("#m2aSaveState")).to_have_text("сохранено");page.close()


def test_m2a_batch_cancel_preserves_completed_results(browser)->None:
    page=browser.new_page(viewport={"width":1280,"height":900});project,process_calls=_load(page);page.locator('[data-module="batch"]').click();page.locator("#m2aBatchAll").click();page.locator("#m2aRunBatch").click();expect.poll(lambda:len(process_calls),timeout=10000).to_be_greater_than(0);page.evaluate("window.imagelabM2A.batch.cancelled = true");expect(page.locator("#m2aBatchJob span").first).to_have_text("Отменено",timeout=10000);assert 1<=len(process_calls)<3;assert any(item.get("status")=="CANCELLED" for report in project["workspace"].get("batch_reports",[]) for item in report.get("items",[]));expect(page.locator('#m2aBatchReport [data-status="PASS"]')).to_have_count(len(process_calls));expect(page.locator('#m2aBatchReport [data-status="CANCELLED"]')).to_have_count(1);page.close()
