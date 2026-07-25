const PROJECT_ID = 'TS-001';
const state = {
  project: null,
  selectedId: null,
  busy: false,
  module: 'upload',
  extractMode: 'auto',
  selectionMode: 'object',
  halftoneMode: 'color',
  raster: 'dot',
  vectorMode: 'color',
  exportFormat: 'PNG',
  aiAnalysis: null,
  aiHealth: null,
  selectionTool: 'brush',
  selectionEdits: [],
  selectionDraft: null,
  selectionAssetId: null,
  halftonePreview: 'transparent',
  activeSelectionEpoch: 0,
  pendingSelectionId: null,
  operationMode: 'professional',
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const moduleMeta = {
  upload:['1.','Загрузка','Исходные изображения проекта'],
  improve:['2.','Улучшение','Качество, реконструкция и детализация'],
  extract:['3.','Достать принт','Извлечение принта с изделия в отдельный PNG'],
  selection:['4.','Выделение','Объект, принт или элемент с ручной коррекцией'],
  cleanup:['5.','Очистка','Фон, ореол, цвет и дефекты'],
  halftone:['6.','Полутон','Точечный, линейный и гибридный растр'],
  vector:['7.','Векторизация','Цветной или монохромный SVG'],
  geometry:['8.','Размер и холст','Миллиметры, PPI и геометрия'],
  export:['9.','Экспорт','Форматы, QA, отчёт и ZIP проекта'],
};
const operationNames = {
  enhance:'Улучшение', reconstruct:'Реконструкция', extract_print:'Извлечение принта', select:'Выделение',
  background:'Удаление фона', cleanup:'Очистка', geometry:'Геометрия', color:'Цвет', halftone:'Полутон',
  vectorize:'Векторизация', export:'Экспорт', master_clean:'Clean Master', master_card:'Card Master', master_dtf:'DTF Master'
};
const feedbackModuleMap = {upload:'upload',improve:'improve',extract:'extract',selection:'selection',cleanup:'cleanup',halftone:'halftone',vector:'vector',geometry:'geometry',export:'export'};
const aiTaskHints = {
  upload:['content_and_quality'], improve:['restoration'], extract:['print_segmentation'], selection:['subject_segmentation','print_segmentation'],
  cleanup:['subject_segmentation','visual_preflight'], halftone:['halftone_recommendation'], vector:['vector_recommendation'],
  geometry:['layout_assistant'], export:['export_recommendation']
};



function collectAIRecords(value, records = []) {
  if (Array.isArray(value)) value.forEach((item) => collectAIRecords(item, records));
  else if (value && typeof value === 'object') {
    if (value.model_id && value.model_version) records.push(value);
    Object.values(value).forEach((item) => collectAIRecords(item, records));
  }
  return records;
}
function primaryAIRecord(asset, module = state.module) {
  const records = collectAIRecords(asset?.ai || {});
  const hints = aiTaskHints[module] || [];
  const matched = records.find((item) => hints.some((hint) => String(item.task || '').includes(hint)));
  return matched || records.find((item) => Array.isArray(item?.details?.features)) || records[0] || null;
}
function aiFeatures(asset) {
  const record = state.aiAnalysis || primaryAIRecord(asset);
  return Array.isArray(record?.details?.features) ? record.details.features : null;
}
function renderAI(asset) {
  const record = state.aiAnalysis || primaryAIRecord(asset);
  const values = record ? [record.model_id, record.model_version, `${Math.round((record.confidence || 0) * 100)}%`, record.provider, `${record.runtime_ms || 0} ms`, (record.input_sha256 || '').slice(0, 16)] : ['—','—','—','—','—','—'];
  ['aiModelValue','aiVersionValue','aiConfidenceValue','aiProviderValue','aiRuntimeValue','aiHashValue'].forEach((id,index)=>{ const node=document.getElementById(id); if(node) node.textContent=values[index]; });
  $('#aiPanelTitle').textContent = record ? (record.task || 'AI-контур') : 'AI-контур';
  $('#aiPanelStatus').textContent = record ? `${collectAIRecords(asset?.ai || {}).length || 1} inference-записей · evidence сохранён` : 'Выберите файл для просмотра evidence.';
}
async function loadAIHealth() {
  try {
    const [health, runtime] = await Promise.all([api('/api/ai/health'), api('/api/health')]);
    state.aiHealth = health;
    $('#aiHealthChip').classList.toggle('ready', health.status === 'ready'); $('#aiHealthChip').classList.toggle('failed', health.status !== 'ready');
    $('#aiHealthText').textContent = health.status === 'ready' ? `${health.models.length} моделей · CPU` : 'ошибка';
    const versionNode = $('#buildVersionChip');
    if (versionNode) {
      versionNode.textContent = `версия ${runtime.version} · ${String(runtime.install_id || 'source').slice(0, 8)}`;
      versionNode.title = `Build: ${runtime.build_id || '—'}\nInstall ID: ${runtime.install_id || '—'}`;
      versionNode.dataset.scope = runtime.scope || '';
      versionNode.classList.toggle('ready', runtime.status === 'ok');
      versionNode.classList.toggle('failed', runtime.status !== 'ok');
    }
  } catch (error) {
    $('#aiHealthChip').classList.add('failed'); $('#aiHealthText').textContent = 'недоступен';
    const versionNode = $('#buildVersionChip'); if (versionNode) { versionNode.textContent = 'версия не определена'; versionNode.classList.add('failed'); }
  }
}
async function analyzeSelectedAI(module = state.module) {
  const asset = requireAsset(); if (!asset || asset.format === 'SVG') { if(asset?.format==='SVG') toast('Для растрового AI-анализа выберите PNG/JPG', true); return; }
  setBusy(true);
  try { state.aiAnalysis = await api(`/api/assets/${asset.id}/ai/analyze?module=${encodeURIComponent(module)}`, {method:'POST'}); renderAI(asset); activateInfoTab('ai'); toast(`AI-анализ: ${module}`); }
  catch(error){ toast(error.message,true); } finally { setBusy(false); }
}
async function explainSelectedAI() {
  const asset=requireAsset(); if(!asset || asset.format==='SVG') return;
  setBusy(true); try { const result=await api(`/api/assets/${asset.id}/ai/explain`); $('#aiExplanation').textContent=`${result.text}

Confidence: ${Math.round((result.confidence||0)*100)}%
Evidence: ${JSON.stringify(result.evidence,null,2)}`; activateInfoTab('ai'); }
  catch(error){toast(error.message,true);} finally{setBusy(false);}
}
async function storeAIFeedback(accepted) {
  const asset=requireAsset(); const features=aiFeatures(asset); if(!asset || !features){toast('Сначала выполните AI-анализ',true);return;}
  const module=feedbackModuleMap[state.module] || 'upload'; setBusy(true);
  try { await api('/api/ai/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({module,asset_id:asset.id,accepted,features,note:`UI feedback for ${asset.operation||'upload'}`,operation:asset.operation||'upload',quality_score:Number(asset.parameters?.repair_quality_score ?? 0),evidence_codes:asset.parameters?.repair_defects||[],parameters:asset.parameters||{}})}); toast(accepted?'Результат принят в датасет':'Результат отклонён и сохранён'); }
  catch(error){toast(error.message,true);} finally { setBusy(false); }
}
async function trainAIModule() {
  const module=feedbackModuleMap[state.module] || 'upload';
  if (!confirm(`Обучить кандидат модели для модуля «${module}» и активировать его только при прохождении benchmark?`)) return;
  setBusy(true);
  try { const result=await api('/api/ai/train',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({module})}); $('#aiExplanation').textContent=JSON.stringify(result,null,2); toast(result.status==='promoted'?'Модель прошла benchmark и активирована':'Кандидат не активирован',result.status!=='promoted'); }
  catch(error){toast(error.message,true);} finally{setBusy(false);}
}
async function rollbackAIModule() {
  const module=feedbackModuleMap[state.module] || 'upload';
  if (!confirm(`Откатить активную AI-модель модуля «${module}» к предыдущей версии?`)) return;
  setBusy(true);
  try { const result=await api('/api/ai/rollback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({module})}); $('#aiExplanation').textContent=JSON.stringify(result,null,2); toast('Предыдущая модель восстановлена'); }
  catch(error){toast(error.message,true);} finally{setBusy(false);}
}

async function api(url, options = {}) {
  const response = await fetch(url, {cache:'no-store', ...options});
  const contentType = response.headers.get('content-type') || '';
  let payload;
  try {
    payload = contentType.includes('application/json') ? await response.json() : await response.text();
  } catch (error) {
    throw new Error(`Сервер вернул повреждённый ответ (${response.status})`);
  }
  if (!response.ok) throw new Error(payload?.detail || payload || `Ошибка запроса (${response.status})`);
  return payload;
}
function number(selector, fallback = 0) {
  const node = $(selector); const value = Number.parseFloat(node?.value);
  return Number.isFinite(value) ? value : fallback;
}
function effectiveAutoRepair() {
  if (state.operationMode === 'fast' || state.operationMode === 'check-only') return false;
  return $('#globalAutoRepair')?.checked ?? true;
}
function fmtBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  const units = ['Б','КБ','МБ','ГБ']; let value = bytes; let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index && value < 10 ? 1 : 0)} ${units[index]}`;
}
function toast(message, error = false) {
  const node = $('#toast'); node.textContent = message; node.classList.toggle('error', error); node.classList.add('show');
  clearTimeout(node._timer); node._timer = setTimeout(() => node.classList.remove('show'), 2800);
}
function selectedAsset() { return state.project?.assets?.find((asset) => asset.id === state.selectedId) || null; }
function sourceAsset(asset) { return asset?.source_asset_id ? state.project?.assets?.find((item) => item.id === asset.source_asset_id) : null; }
function requireAsset() { const asset = selectedAsset(); if (!asset) toast('Сначала загрузите или выберите файл', true); return asset; }
function resetSelectionState(assetId = null) { state.selectionEdits = []; state.selectionDraft = null; state.selectionAssetId = assetId; }
function setBusy(flag) {
  state.busy = flag;
  $('#busyOverlay').classList.toggle('show', flag); $('#busyOverlay').setAttribute('aria-hidden', flag ? 'false' : 'true');
  document.body.setAttribute('aria-busy', flag ? 'true' : 'false');
  const ids = ['refreshButton','chooseButton','clearButton','applyEnhance','applyReconstruct','applyExtractPrint','applySelection','applyCleanup','applyHalftone','applyVectorize','applyGeometry','applyExport','runQaButton','runReportButton','aiAnalyzeSelected','aiExplainSelected','aiAccept','aiReject','aiTrainButton','aiRollbackButton'];
  ids.forEach((id) => { const node = document.getElementById(id); if (node) node.disabled = flag; });
  ['bundleButton','cardlabButton'].forEach((id) => { const node=document.getElementById(id); if(node){ node.setAttribute('aria-disabled', flag ? 'true' : 'false'); node.classList.toggle('disabled-link', flag); } });
  if (!flag) {
    syncLocks();
    if (state.pendingSelectionId) {
      const pending = state.pendingSelectionId;
      state.pendingSelectionId = null;
      queueMicrotask(() => pinActiveAsset(pending));
    }
  }
}
function syncLocks() {
  const hasAsset = Boolean(selectedAsset()); const hasAssets = Boolean(state.project?.assets?.length);
  $('#downloadButton').disabled = !hasAsset; $('#sourceButton').disabled = !sourceAsset(selectedAsset()); $('#clearButton').disabled = !hasAssets;
  ['applyEnhance','applyReconstruct','applyExtractPrint','applySelection','applyCleanup','applyHalftone','applyVectorize','applyGeometry','applyExport','runQaButton','runReportButton','aiAnalyzeSelected','aiExplainSelected','aiAccept','aiReject'].forEach((id) => {
    const node = document.getElementById(id); if (node) node.disabled = !hasAsset;
  });
  $('#bundleButton').href = `/api/projects/${PROJECT_ID}/bundle`;
  const bundle=$('#bundleButton'); bundle.setAttribute('aria-disabled', hasAssets && !state.busy ? 'false' : 'true'); bundle.classList.toggle('disabled-link', !hasAssets || state.busy);
  const cardlab=$('#cardlabButton'); cardlab.setAttribute('aria-disabled', hasAsset && !state.busy ? 'false' : 'true'); cardlab.classList.toggle('disabled-link', !hasAsset || state.busy);
}
function activateModule(module) {
  state.module = module;
  $$('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.module === module));
  $$('.module-pane').forEach((pane) => pane.classList.toggle('active', pane.dataset.pane === module));
  const [numberValue,title,subtitle] = moduleMeta[module];
  $('#moduleNumber').textContent = numberValue; $('#moduleTitle').textContent = title; $('#moduleSubtitle').textContent = subtitle;
  const trainingModule = feedbackModuleMap[module] || 'upload';
  if ($('#aiTrainModule')) { $('#aiTrainModule').value = trainingModule; $('#aiTrainModule').disabled = true; }
  state.aiAnalysis = null; renderAI(selectedAsset());
  const canvas = activePreviewCanvas(); if (canvas) canvas.style.pointerEvents = module === 'selection' ? 'auto' : 'none';
  if (module === 'selection') drawSelectionOverlay();
}
function activateInfoTab(name) {
  $$('.info-tab').forEach((button) => button.classList.toggle('active', button.dataset.infoTab === name));
  $('#infoContent').classList.toggle('active', name === 'info'); $('#checksContent').classList.toggle('active', name === 'checks'); $('#reportContent').classList.toggle('active', name === 'report'); $('#aiContent').classList.toggle('active', name === 'ai');
}
function buildPointGrid(containerId, prefix) {
  const root = document.getElementById(containerId); root.replaceChildren();
  [['TL',0,0],['TR',100,0],['BR',100,100],['BL',0,100]].forEach(([name,x,y]) => {
    const block = document.createElement('div'); block.innerHTML = `<label>${name} X<input id="${prefix}${name}x" type="number" min="0" max="100" value="${x}"></label><label>${name} Y<input id="${prefix}${name}y" type="number" min="0" max="100" value="${y}"></label>`; root.append(block);
  });
}
function pointValues(prefix) { return ['TL','TR','BR','BL'].map((name) => [number(`#${prefix}${name}x`), number(`#${prefix}${name}y`)]); }
function improvePhysicalParams() {
  return {
    width_mm: $('#improveWidthMm')?.value || '',
    height_mm: $('#improveHeightMm')?.value || '',
    ppi: number('#improvePpi', 300),
    preserve_aspect: $('#improvePreserveAspect')?.checked ?? true,
  };
}
function updateImproveEstimate() {
  const widthMm = number('#improveWidthMm', 0); const heightMm = number('#improveHeightMm', 0); const ppi = number('#improvePpi', 300);
  const node = $('#improvePixelEstimate'); if (!node) return;
  if (ppi < 100 || ppi > 1000) { node.textContent = 'PPI/DPI должен быть от 100 до 1000.'; node.classList.add('warning-text'); return; }
  node.classList.remove('warning-text');
  if (!widthMm && !heightMm) { node.textContent = 'Пиксельный размер будет рассчитан из мм и PPI.'; return; }
  const asset = selectedAsset(); let w = widthMm; let h = heightMm;
  if ($('#improvePreserveAspect')?.checked && asset?.width_px && asset?.height_px) {
    if (w && !h) h = w * asset.height_px / asset.width_px;
    else if (h && !w) w = h * asset.width_px / asset.height_px;
    else if (w && h) h = w * asset.height_px / asset.width_px;
  }
  if (!w || !h) { node.textContent = 'Укажите ширину или высоту в мм.'; return; }
  node.textContent = `Итог: ${Math.round(w / 25.4 * ppi)} × ${Math.round(h / 25.4 * ppi)} px при ${ppi} PPI.`;
}
function activePreviewCanvas() { return document.querySelector('#previewStage canvas.selection-canvas'); }
function selectionBrushPixels(asset = selectedAsset()) {
  const ppi = Number(asset?.ppi_x || 300); return Math.max(1, number('#selectionBrushMm', 5) / 25.4 * ppi);
}
function drawSelectionOverlay() {
  const canvas = activePreviewCanvas(); if (!canvas) return; const ctx = canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height);
  const edits = [...state.selectionEdits, ...(state.selectionDraft ? [state.selectionDraft] : [])];
  const toPoint = (point) => [point[0] * canvas.width, point[1] * canvas.height];
  edits.forEach((edit) => {
    const points = edit.points || []; if (!points.length) return;
    const erase = edit.tool === 'erase'; ctx.save(); ctx.strokeStyle = erase ? 'rgba(255,80,80,.9)' : 'rgba(45,155,255,.95)'; ctx.fillStyle = erase ? 'rgba(255,80,80,.25)' : 'rgba(45,155,255,.25)'; ctx.lineWidth = selectionBrushPixels(); ctx.lineCap='round'; ctx.lineJoin='round';
    if (edit.tool === 'rectangle' && points.length >= 2) { const [a,b]=points.map(toPoint); ctx.fillRect(Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1])); ctx.strokeRect(Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1])); }
    else if (edit.tool === 'lasso' && points.length >= 3) { ctx.beginPath(); const first=toPoint(points[0]); ctx.moveTo(...first); points.slice(1).forEach((p)=>ctx.lineTo(...toPoint(p))); ctx.closePath(); ctx.fill(); ctx.stroke(); }
    else { ctx.beginPath(); const first=toPoint(points[0]); ctx.moveTo(...first); points.slice(1).forEach((p)=>ctx.lineTo(...toPoint(p))); if(points.length===1){ctx.lineTo(first[0]+.01,first[1]+.01);} ctx.stroke(); }
    ctx.restore();
  });
}
function setupSelectionCanvas(canvas) {
  const image = canvas.previousElementSibling; if (!image) return;
  canvas.width = image.naturalWidth || selectedAsset()?.width_px || 1; canvas.height = image.naturalHeight || selectedAsset()?.height_px || 1;
  canvas.style.pointerEvents = state.module === 'selection' ? 'auto' : 'none'; drawSelectionOverlay();
  const normalized = (event) => { const rect=canvas.getBoundingClientRect(); if(!rect.width || !rect.height) return [0,0]; return [Math.min(1,Math.max(0,(event.clientX-rect.left)/rect.width)),Math.min(1,Math.max(0,(event.clientY-rect.top)/rect.height))]; };
  canvas.onpointerdown = (event) => { if(state.module!=='selection')return; canvas.setPointerCapture(event.pointerId); const p=normalized(event); state.selectionDraft={tool:state.selectionTool,points:[p]}; drawSelectionOverlay(); };
  canvas.onpointermove = (event) => { if(!state.selectionDraft)return; const p=normalized(event); if(state.selectionTool==='rectangle') state.selectionDraft.points=[state.selectionDraft.points[0],p]; else state.selectionDraft.points.push(p); drawSelectionOverlay(); };
  const finish = (event) => { if(canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId); if(!state.selectionDraft)return; if(state.selectionDraft.tool==='lasso' && state.selectionDraft.points.length<3){state.selectionDraft=null;drawSelectionOverlay();return;} if(state.selectionDraft.tool==='rectangle' && state.selectionDraft.points.length<2){state.selectionDraft=null;drawSelectionOverlay();return;} state.selectionEdits.push(state.selectionDraft); state.selectionDraft=null; drawSelectionOverlay(); };
  canvas.onpointerup=finish; canvas.onpointercancel=finish;
}
function bindRanges() {
  $$('input[type=range]').forEach((input) => {
    const output = document.querySelector(`output[data-for="${input.id}"]`); if (!output) return;
    const render = () => {
      let suffix = '%';
      if (input.id.includes('Feather')) suffix = ' px';
      if (input.id === 'halftoneAlphaThreshold') suffix = '';
      output.value = `${input.value}${suffix}`;
    };
    input.addEventListener('input', render); render();
  });
}

function metadataValues(asset) {
  if (!asset) return Array(8).fill('—');
  return [
    asset.print_width_mm ? `${asset.print_width_mm} мм` : '—',
    asset.print_height_mm ? `${asset.print_height_mm} мм` : '—',
    asset.ppi_x ? `${asset.ppi_x} PPI` : '—',
    asset.print_width_mm && asset.print_height_mm ? `${asset.print_width_mm} × ${asset.print_height_mm} мм` : '—',
    asset.format || '—', asset.color_profile || '—', asset.has_alpha ? 'Есть' : 'Нет', fmtBytes(asset.size_bytes),
  ];
}
function renderMetadata(asset) { const values = metadataValues(asset); $$('#metadata dd').forEach((node,index) => { node.textContent = values[index] || '—'; }); }
function createCheckNode(check) {
  const row = document.createElement('div'); row.className = `check-item${check.passed ? '' : ' fail'}`;
  const icon = document.createElement('span'); icon.className = 'check-icon'; icon.textContent = check.passed ? '✓' : '!';
  const text = document.createElement('span'); text.textContent = check.detail ? `${check.label}: ${check.detail}` : check.label;
  row.append(icon,text); return row;
}
function renderChecks(checks = []) {
  const root = $('#checkList'); root.replaceChildren();
  if (!checks.length) { const empty = document.createElement('span'); empty.className = 'empty-note'; empty.textContent = 'Нет данных'; root.append(empty); return; }
  checks.forEach((check) => root.append(createCheckNode(check)));
}
function syncGeometry(asset) {
  if (!asset) return;
  if (document.activeElement !== $('#widthMm')) $('#widthMm').value = asset.print_width_mm || '';
  if (document.activeElement !== $('#heightMm')) $('#heightMm').value = asset.print_height_mm || '';
  if (document.activeElement !== $('#geometryPpi')) $('#geometryPpi').value = asset.ppi_x || 300;
}
function renderHistory() {
  const root = $('#historyStrip'); root.replaceChildren(); const assets = state.project?.assets || [];
  $('#assetCount').textContent = `${assets.length} файлов`; $('#historyCount').textContent = `${assets.length}`;
  if (!assets.length) { const empty = document.createElement('span'); empty.className = 'empty-note'; empty.textContent = 'История пуста'; root.append(empty); return; }
  assets.forEach((asset) => {
    const button = document.createElement('button'); button.className = `history-thumb${asset.id === state.selectedId ? ' active' : ''}`; button.type = 'button'; button.dataset.assetId = asset.id; button.setAttribute('aria-pressed', asset.id === state.selectedId ? 'true' : 'false');
    const image = document.createElement('img'); image.src = `${asset.preview_url}?sha=${encodeURIComponent(asset.sha256 || asset.id)}`; image.alt = asset.original_name; button.title = `${asset.original_name} — выбрать этот файл`;
    const tag = document.createElement('em'); tag.textContent = asset.operation ? (operationNames[asset.operation] || asset.operation) : asset.format;
    button.append(image,tag); button.addEventListener('click', async (event) => { event.preventDefault(); event.stopPropagation(); await pinActiveAsset(asset.id); }); root.append(button);
  });
}

function renderResultEvidence(asset) {
  const node = $('#resultEvidence'); if (!node) return;
  if (!asset) { node.textContent = 'Выберите или создайте файл — здесь появятся фактические размеры и PPI.'; return; }
  const p = asset.parameters || {};
  const input = p.input_width_px && p.input_height_px ? `${p.input_width_px} × ${p.input_height_px} px · ${p.input_ppi ?? '—'} PPI` : 'исходные параметры не записаны';
  const result = asset.width_px && asset.height_px ? `${asset.width_px} × ${asset.height_px} px · ${asset.ppi_x ?? '—'} PPI` : 'размер не определён';
  const flags = [];
  if (p.pixel_dimensions_changed === true) flags.push('пиксели изменены');
  if (p.pixel_dimensions_changed === false && asset.operation) flags.push('пиксели без изменения');
  if (p.ppi_changed === true) flags.push('PPI изменён');
  if (p.ppi_changed === false && asset.operation) flags.push('PPI без изменения');
  node.textContent = asset.operation ? `Вход: ${input} → результат: ${result}${flags.length ? ` · ${flags.join(', ')}` : ''}` : `Файл: ${result}`;
}

function renderPreview() {
  const asset = selectedAsset(); const stage = $('#previewStage'); stage.replaceChildren();
  if (!asset) {
    resetSelectionState(null);
    stage.innerHTML = '<div class="empty-preview"><span>IL</span><p>Загрузите изображение</p></div>';
    $('#previewTitle').textContent = 'Предпросмотр'; $('#previewOperation').textContent = 'Исходный файл'; $('#previewDimensions').textContent = 'Размер не указан'; $('#previewFormat').textContent = '—';
    renderMetadata(null); renderChecks([]); renderResultEvidence(null); state.aiAnalysis=null; renderAI(null); $('#activeInputName').textContent='Файл не выбран'; $('#activeInputLineage').textContent='—'; return;
  }
  if (state.selectionAssetId !== asset.id) resetSelectionState(asset.id);
  const previewUrl = `${asset.preview_url}?sha=${encodeURIComponent(asset.sha256 || asset.id)}`;
  if (asset.format === 'SVG') {
    const wrap=document.createElement('div'); wrap.className='preview-image-wrap';
    const image=document.createElement('img'); image.src=previewUrl; image.alt=`SVG: ${asset.original_name}`;
    image.addEventListener('error',()=>toast('SVG создан, но браузер не смог показать предпросмотр. Используйте кнопку «Экспорт».',true));
    wrap.append(image); stage.append(wrap);
  }
  else { const wrap=document.createElement('div'); wrap.className='preview-image-wrap'; const image = document.createElement('img'); image.src = previewUrl; image.alt = asset.original_name; const canvas=document.createElement('canvas'); canvas.className='selection-canvas'; wrap.append(image,canvas); stage.append(wrap); image.addEventListener('load',()=>setupSelectionCanvas(canvas)); }
  $('#previewTitle').textContent = asset.original_name;
  const revision = state.project?.workspace?.active_revision ?? 0;
  $('#previewOperation').textContent = `${asset.operation ? (operationNames[asset.operation] || asset.operation) : 'Исходный файл'} · активный файл · rev ${revision}`;
  $('#previewDimensions').textContent = asset.width_px && asset.height_px ? `${asset.width_px} × ${asset.height_px} px` : 'Размер не указан'; $('#previewFormat').textContent = asset.format;
  renderMetadata(asset); renderChecks(asset.checks || []); renderResultEvidence(asset); state.aiAnalysis=null; renderAI(asset); syncGeometry(asset); if (!$('#improveWidthMm').value) $('#improveWidthMm').value = asset.print_width_mm || ''; if (!$('#improveHeightMm').value) $('#improveHeightMm').value = asset.print_height_mm || ''; if (document.activeElement !== $('#improvePpi')) $('#improvePpi').value = Math.min(1000,Math.max(100,asset.ppi_x || 300)); updateImproveEstimate(); $('#activeInputName').textContent=asset.original_name; $('#activeInputLineage').textContent=asset.source_asset_id?'производный файл':'исходник';
}
function renderProject() { $('#projectName').textContent = state.project?.title || PROJECT_ID; renderHistory(); renderPreview(); syncLocks(); }

async function pinActiveAsset(assetId) {
  if (!assetId) return;
  if (state.busy) {
    state.pendingSelectionId = assetId;
    toast('Переключение будет выполнено сразу после текущей операции');
    return;
  }
  const previousId = state.selectedId;
  const epoch = ++state.activeSelectionEpoch;
  // Switch immediately so the history does not feel unresponsive. The server
  // remains the source of truth and can roll the selection back on failure.
  state.selectedId = assetId; renderProject();
  try {
    const project = await api(`/api/projects/${PROJECT_ID}/active`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:assetId})});
    if (epoch !== state.activeSelectionEpoch) return;
    state.project = project;
    const confirmed = project.workspace?.active_asset_id;
    state.selectedId = project.assets?.some((asset)=>asset.id===confirmed) ? confirmed : assetId;
    renderProject();
  } catch (error) {
    if (epoch === state.activeSelectionEpoch) { state.selectedId = previousId; renderProject(); }
    toast(error.message, true);
  }
}
async function divertCheckOnly(actionLabel) {
  if (state.operationMode !== 'check-only') return false;
  toast(`Режим «Только проверка»: ${actionLabel} не изменяет проект`);
  await runQa();
  return true;
}

async function loadProject() {
  try {
    state.project = await api(`/api/projects/${PROJECT_ID}`);
    const pinned = state.project.workspace?.active_asset_id;
    state.selectedId = state.project.assets?.some((asset)=>asset.id===pinned) ? pinned : (state.project.assets?.at(-1)?.id || null);
    renderProject();
  } catch (error) { toast(error.message, true); }
}
async function uploadFiles(files) {
  if (!files?.length || state.busy) return; const form = new FormData(); [...files].forEach((file) => form.append('files', file)); setBusy(true);
  try { const result = await api(`/api/projects/${PROJECT_ID}/upload`, {method:'POST',body:form}); state.project = result.project; state.selectedId = result.uploaded.at(-1)?.id || null; renderProject(); toast(`Загружено: ${result.uploaded.length}`); }
  catch (error) { toast(error.message, true); }
  finally { setBusy(false); $('#fileInput').value = ''; }
}
async function processSelected(operation, parameters, message) {
  if (await divertCheckOnly(operationNames[operation] || operation)) return null;
  const asset = requireAsset(); if (!asset || state.busy) return null; setBusy(true);
  try {
    const result = await api(`/api/projects/${PROJECT_ID}/process`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:asset.id,operation,parameters:{...parameters,auto_repair:effectiveAutoRepair()}})});
    if (result.source_asset_id !== asset.id) throw new Error('Сервер обработал не выбранный файл; операция заблокирована');
    state.project = result.project;
    state.selectedId = result.result.id;
    renderProject();
    const repairNote=result.repair?.attempt_count>1?` · автоисправлений: ${result.repair.attempt_count-1}`:'';
    const repairFailed=result.repair && result.repair.passed===false;
    const actual = result.result.format === 'SVG'
      ? `SVG ${result.result.width_px || '—'} × ${result.result.height_px || '—'} px`
      : `${result.result.width_px || '—'} × ${result.result.height_px || '—'} px · ${result.result.ppi_x || '—'} PPI`;
    const okText = `${message || `${operationNames[operation] || operation}: готово`} · ${actual}${repairNote}`;
    toast(repairFailed ? `Результат создан, но заблокирован QA · ${actual}${repairNote}` : okText, repairFailed);
    if(result.repair) $('#aiExplanation').textContent=JSON.stringify(result.repair,null,2);
    return result.result;
  } catch (error) { toast(error.message, true); return null; }
  finally { setBusy(false); }
}
async function applyCleanupFlow() {
  if (await divertCheckOnly('Очистка')) return;
  const asset = requireAsset(); if (!asset || state.busy) return;
  const removeBackground = $('#removeBackground').checked;
  const runCleanup = $('#removeHalo').checked || $('#removeColor').checked || $('#cleanupDefects').checked;
  if (!removeBackground && !runCleanup) { toast('Выберите хотя бы одно действие очистки', true); return; }
  setBusy(true);
  try {
    const autoRepair=effectiveAutoRepair();
    const response = await api(`/api/projects/${PROJECT_ID}/cleanup-pipeline`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        asset_id:asset.id,
        remove_background:removeBackground,
        background_parameters:{action:'remove',mode:'object',feather:number('#backgroundFeather',2),ai_auto:$('#cleanupAiAuto').checked,auto_repair:autoRepair},
        run_cleanup:runCleanup,
        cleanup_parameters:{remove_halo:$('#removeHalo').checked,remove_color:$('#removeColor').checked,target_color:$('#cleanupColor').value,tolerance:number('#cleanupTolerance',18),defect_cleanup:$('#cleanupDefects').checked?35:0,binary_alpha:$('#cleanupBinaryAlpha').checked,alpha_threshold:128,ai_auto:$('#cleanupAiAuto').checked,auto_repair:autoRepair}
      })
    });
    if (response.source_asset_id !== asset.id || response.atomic !== true) throw new Error('Сервер не подтвердил атомарную очистку выбранного файла');
    state.project = response.project; state.selectedId = response.result.id; renderProject();
    const reports=response.repairs||[]; const failed=reports.some((item)=>item.passed===false); const retries=reports.reduce((sum,item)=>sum+Math.max(0,(item.attempt_count||1)-1),0);
    $('#aiExplanation').textContent=JSON.stringify({cleanup_pipeline:reports,atomic:true},null,2);
    toast(`Очистка применена атомарно${retries?` · автоисправлений: ${retries}`:''}${failed?' · качество не прошло gate':''}`,failed);
  } catch (error) { toast(error.message, true); }
  finally { setBusy(false); }
}

async function exportSelected() {
  if (await divertCheckOnly('Экспорт')) return;
  const asset = requireAsset(); if (!asset || state.busy) return; setBusy(true);
  try {
    const result = await api(`/api/projects/${PROJECT_ID}/export`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:asset.id,format:state.exportFormat,parameters:{ppi:number('#exportPpi',300),quality:number('#exportQuality',92),keep_alpha:$('#exportAlpha').checked,ai_auto:$('#exportAiAuto').checked}})});
    if (result.source_asset_id !== asset.id) throw new Error('Сервер экспортировал не выбранный файл; операция заблокирована');
    state.project = result.project; state.selectedId = result.result.id; renderProject(); toast('Экспортный файл создан');
  } catch (error) { toast(error.message, true); }
  finally { setBusy(false); }
}
async function runQa() {
  const asset = requireAsset(); if (!asset || state.busy) return; setBusy(true);
  try { const result = await api(`/api/projects/${PROJECT_ID}/qa?asset_id=${encodeURIComponent(asset.id)}`); renderChecks(result.checks); $('#reportBox').textContent = JSON.stringify(result,null,2); activateInfoTab('checks'); toast(result.overall_passed?'QA пройден':'QA обнаружил замечания',!result.overall_passed); }
  catch (error) { toast(error.message,true); } finally { setBusy(false); }
}
async function runReport() {
  if (state.busy) return; setBusy(true);
  try { const asset = selectedAsset(); const suffix = asset?`?asset_id=${encodeURIComponent(asset.id)}`:''; const result = await api(`/api/projects/${PROJECT_ID}/report${suffix}`); $('#reportBox').textContent = JSON.stringify(result,null,2); activateInfoTab('report'); toast('Отчёт сформирован'); }
  catch (error) { toast(error.message,true); } finally { setBusy(false); }
}

$$('.nav-item').forEach((button) => button.addEventListener('click', () => activateModule(button.dataset.module)));
$$('.info-tab').forEach((button) => button.addEventListener('click', () => activateInfoTab(button.dataset.infoTab)));
$('#refreshButton').addEventListener('click', loadProject);
$('#downloadButton').addEventListener('click', () => { const asset = selectedAsset(); if (asset) window.location.href = asset.download_url || `/api/assets/${asset.id}/file`; });
$('#sourceButton').addEventListener('click', async () => { const source = sourceAsset(selectedAsset()); if (source) await pinActiveAsset(source.id); });
$('#chooseButton').addEventListener('click', (event) => { event.stopPropagation(); $('#fileInput').click(); });
$('#dropzone').addEventListener('click', () => $('#fileInput').click()); $('#dropzone').addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('#fileInput').click(); } }); $('#fileInput').addEventListener('change', () => uploadFiles($('#fileInput').files));
['dragenter','dragover'].forEach((name) => $('#dropzone').addEventListener(name,(event)=>{event.preventDefault();$('#dropzone').classList.add('dragover');}));
['dragleave','drop'].forEach((name) => $('#dropzone').addEventListener(name,(event)=>{event.preventDefault();$('#dropzone').classList.remove('dragover');}));
$('#dropzone').addEventListener('drop',(event)=>uploadFiles(event.dataTransfer.files));
$('#clearButton').addEventListener('click', async () => { if (await divertCheckOnly('Очистка проекта')) return; if (!confirm('Удалить все файлы проекта TS-001?')) return; setBusy(true); try { state.project = await api(`/api/projects/${PROJECT_ID}/assets`,{method:'DELETE'}); state.selectedId = null; renderProject(); toast('Проект очищен'); } catch(error){toast(error.message,true);} finally{setBusy(false);} });

$$('[data-improve-mode]').forEach((button)=>button.addEventListener('click',()=>{ $$('[data-improve-mode]').forEach((item)=>item.classList.toggle('active',item===button)); $('#improveManual').classList.toggle('compact-hidden',button.dataset.improveMode==='quick'); }));
$('#applyEnhance').addEventListener('click',()=>processSelected('enhance',{preset:$('#enhancePreset').value,brightness:1,contrast:number('#enhanceContrast',100)/100,saturation:number('#enhanceSaturation',100)/100,sharpness:number('#enhanceSharpness',100)/100,denoise:number('#enhanceDenoise',0),ai_auto:$('#improveAiAuto').checked,...improvePhysicalParams()},'Улучшение применено'));
$('#applyReconstruct').addEventListener('click',()=>processSelected('reconstruct',{scale:number('#reconstructScale',2),detail:number('#reconstructDetail',50),denoise:number('#enhanceDenoise',20),ai_auto:$('#improveAiAuto').checked,...improvePhysicalParams()},'Реконструкция завершена'));

$$('[data-extract-mode]').forEach((button)=>button.addEventListener('click',()=>{ state.extractMode=button.dataset.extractMode; $$('[data-extract-mode]').forEach((item)=>item.classList.toggle('active',item===button)); $('#extractRegionControls').classList.toggle('compact-hidden',state.extractMode!=='region'); }));
$('#applyExtractPrint').addEventListener('click',()=>{
  const params={mode:state.extractMode,x:number('#extractX',10),y:number('#extractY',10),width:number('#extractWidth',80),height:number('#extractHeight',80),sensitivity:number('#extractSensitivity',58),texture_reduction:number('#extractTexture',35),reduce_fabric_texture:number('#extractTexture',35)>0,feather:number('#extractFeather',1),crop_output:$('#extractCrop').checked,padding_mm:number('#extractPaddingMm',2)};
  if ($('#extractPerspectiveEnabled').checked) params.perspective=pointValues('ep');
  processSelected('extract_print',params,'Принт извлечён в отдельный PNG');
});

$$('[data-selection-mode]').forEach((button)=>button.addEventListener('click',()=>{ state.selectionMode=button.dataset.selectionMode; $$('[data-selection-mode]').forEach((item)=>item.classList.toggle('active',item===button)); }));
$$('[data-selection-tool]').forEach((button)=>button.addEventListener('click',()=>{ state.selectionTool=button.dataset.selectionTool; $$('[data-selection-tool]').forEach((item)=>item.classList.toggle('active',item===button)); }));
$('#clearSelectionEdits').addEventListener('click',()=>{resetSelectionState(selectedAsset()?.id || null);drawSelectionOverlay();});
$('#applySelection').addEventListener('click',()=>processSelected('select',{mode:state.selectionMode,grow_mm:number('#selectionGrowMm'),brush_mm:number('#selectionBrushMm',5),feather:number('#selectionFeather'),ai_auto:$('#selectionAiAuto').checked,manual_edits:state.selectionEdits},'Выделение сохранено'));
$('#applyCleanup').addEventListener('click',applyCleanupFlow);

$$('[data-halftone-mode]').forEach((button)=>button.addEventListener('click',()=>{ state.halftoneMode=button.dataset.halftoneMode; $$('[data-halftone-mode]').forEach((item)=>item.classList.toggle('active',item===button)); }));
$$('[data-raster]').forEach((button)=>button.addEventListener('click',()=>{ state.raster=button.dataset.raster; $$('[data-raster]').forEach((item)=>item.classList.toggle('active',item===button)); }));
$$('[data-halftone-preview]').forEach((button)=>button.addEventListener('click',()=>{state.halftonePreview=button.dataset.halftonePreview;$$('[data-halftone-preview]').forEach((item)=>item.classList.toggle('active',item===button));$('#previewStage').dataset.previewBackground=state.halftonePreview;}));
$('#applyHalftone').addEventListener('click',()=>processSelected('halftone',{mode:state.halftoneMode,raster:state.raster,size_mm:number('#halftoneSize',.2),lpi:number('#halftoneLpi',45),min_size_mm:number('#halftoneMinSize',.08),max_size_mm:number('#halftoneMaxSize',.4),angle:number('#halftoneAngle',45),shape:$('#halftoneShape').value,density:number('#halftoneDensity',75),alpha_threshold:number('#halftoneAlphaThreshold',8),invert:$('#halftoneInvert').checked,foreground_color:$('#halftoneColor').value,preview_background:state.halftonePreview,ai_auto:$('#halftoneAiAuto').checked},'Полутон создан'));

$$('[data-vector-mode]').forEach((button)=>button.addEventListener('click',()=>{ state.vectorMode=button.dataset.vectorMode; $$('[data-vector-mode]').forEach((item)=>item.classList.toggle('active',item===button)); }));
$('#applyVectorize').addEventListener('click',()=>processSelected('vectorize',{mode:state.vectorMode,colors:number('#vectorColors',6),simplify_mm:number('#vectorSimplifyMm',.2),min_area_mm2:number('#vectorMinAreaMm2',.5),optimize:$('#vectorOptimize').checked,ai_auto:$('#vectorAiAuto').checked},'SVG создан'));

$('#applyGeometry').addEventListener('click',()=>{ const params={width_mm:$('#widthMm').value,height_mm:$('#heightMm').value,ppi:number('#geometryPpi',300),preserve_aspect:$('#preserveAspect').checked,rotate:number('#rotateAngle'),crop:{x:number('#cropX'),y:number('#cropY'),width:number('#cropWidth',100),height:number('#cropHeight',100)},ai_auto_crop:$('#geometryAiCrop').checked}; if($('#usePerspective').checked)params.perspective=pointValues('p'); processSelected('geometry',params,'Размер и геометрия применены'); });
$$('[data-export-format]').forEach((button)=>button.addEventListener('click',()=>{ state.exportFormat=button.dataset.exportFormat; $$('[data-export-format]').forEach((item)=>item.classList.toggle('active',item===button)); }));
$('#applyExport').addEventListener('click',exportSelected); $('#runQaButton').addEventListener('click',runQa); $('#runReportButton').addEventListener('click',runReport);
$('#masterCleanButton').addEventListener('click',()=>processSelected('master_clean',{},'Clean Master создан'));
$('#masterCardButton').addEventListener('click',()=>processSelected('master_card',{width_mm:300,height_mm:400,ppi:300},'Card Master создан'));
$('#masterDtfButton').addEventListener('click',()=>processSelected('master_dtf',{},'DTF Master создан'));
$('#logoPrepareButton').addEventListener('click',()=>processSelected('logo',{remove_background:true,color_mode:'black',binary_alpha:false},'Логотип подготовлен'));
$('#cardlabButton').addEventListener('click',(event)=>{ if(state.busy){event.preventDefault();return;} const asset=selectedAsset(); if(!asset){event.preventDefault();toast('Выберите файл',true);return;} event.currentTarget.href=`/api/projects/${PROJECT_ID}/cardlab-package?asset_id=${encodeURIComponent(asset.id)}`; });
$('#bundleButton').addEventListener('click',(event)=>{if(state.busy || !state.project?.assets?.length)event.preventDefault();});
$('#globalOperationMode').addEventListener('change',(event)=>{
  state.operationMode=event.target.value;
  const checkOnly=state.operationMode==='check-only'; const fast=state.operationMode==='fast'; const auto=state.operationMode==='autoparams';
  $('#globalAutoRepair').disabled=checkOnly || fast;
  if(auto) $$('input[id$="AiAuto"],#geometryAiCrop,#exportAiAuto').forEach((input)=>{input.checked=true;});
  const message=checkOnly?'Включён режим «Только проверка»':fast?'Быстрый режим: повторные автоисправления отключены':auto?'AI-автопараметры включены; числовые ограничения сохраняются':'Профессиональный режим';
  toast(message); syncLocks();
});


$$('[data-ai-analyze]').forEach((button)=>button.addEventListener('click',()=>analyzeSelectedAI(button.dataset.aiAnalyze)));
$('#aiAnalyzeSelected').addEventListener('click',()=>analyzeSelectedAI(state.module));
$('#aiExplainSelected').addEventListener('click',explainSelectedAI);
$('#aiAccept').addEventListener('click',()=>storeAIFeedback(true));
$('#aiReject').addEventListener('click',()=>storeAIFeedback(false));
$('#aiTrainButton').addEventListener('click',trainAIModule);
$('#aiRollbackButton').addEventListener('click',rollbackAIModule);

['#improveWidthMm','#improveHeightMm','#improvePpi'].forEach((selector)=>$(selector)?.addEventListener('input',updateImproveEstimate)); $('#improvePreserveAspect')?.addEventListener('change',updateImproveEstimate);
window.addEventListener('resize',()=>{const canvas=activePreviewCanvas();if(canvas)drawSelectionOverlay();});
buildPointGrid('perspectiveGrid','p'); buildPointGrid('extractPerspectiveGrid','ep'); bindRanges(); activateModule('upload'); loadAIHealth(); loadProject();
