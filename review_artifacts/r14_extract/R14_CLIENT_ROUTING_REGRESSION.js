'use strict';
const assert = require('assert');

function runCase({mode, perspective=false}) {
  const captured = [];
  const controls = {
    '#extractX': 10, '#extractY': 20, '#extractWidth': 70, '#extractHeight': 60,
    '#extractSensitivity': 58, '#extractTexture': 35, '#extractFeather': 1, '#extractPaddingMm': 2,
  };
  const checked = {'#extractCrop': true, '#extractPerspectiveEnabled': perspective};
  const active = mode === 'region';
  const document = {querySelector: () => ({classList:{contains:()=>active}})};
  const state = {};
  const number = (selector, fallback) => controls[selector] ?? fallback;
  const pointValues = () => [[0,0],[100,0],[100,100],[0,100]];
  const $ = (selector) => ({checked: !!checked[selector]});
  const processSelected = (operation, params, message) => captured.push({operation,params,message});

  const regionButton=document.querySelector('[data-extract-mode="region"]');
  const actualMode=regionButton?.classList.contains('active')?'region':'auto';
  state.extractMode=actualMode;
  const params={mode:actualMode,x:number('#extractX',10),y:number('#extractY',10),width:number('#extractWidth',80),height:number('#extractHeight',80),strict_roi:actualMode==='region'};
  if(actualMode==='auto') Object.assign(params,{sensitivity:number('#extractSensitivity',58),texture_reduction:number('#extractTexture',35),reduce_fabric_texture:number('#extractTexture',35)>0,feather:number('#extractFeather',1),crop_output:$('#extractCrop').checked,padding_mm:number('#extractPaddingMm',2)});
  if ($('#extractPerspectiveEnabled').checked) params.perspective=pointValues('ep');
  processSelected('extract_print',params,actualMode==='region'?'Рабочий фрагмент создан':'Принт извлечён в отдельный PNG');
  return captured[0];
}

const cutoutKeys = ['sensitivity','texture_reduction','reduce_fabric_texture','feather','crop_output','padding_mm'];
const region = runCase({mode:'region'});
assert.strictEqual(region.operation, 'extract_print');
assert.strictEqual(region.params.mode, 'region');
assert.strictEqual(region.params.strict_roi, true);
for (const key of cutoutKeys) assert.ok(!(key in region.params), `region leaked ${key}`);
assert.strictEqual(region.message, 'Рабочий фрагмент создан');

const regionPerspective = runCase({mode:'region', perspective:true});
assert.deepStrictEqual(regionPerspective.params.perspective, [[0,0],[100,0],[100,100],[0,100]]);
for (const key of cutoutKeys) assert.ok(!(key in regionPerspective.params), `region+perspective leaked ${key}`);

const auto = runCase({mode:'auto'});
assert.strictEqual(auto.params.mode, 'auto');
assert.strictEqual(auto.params.strict_roi, false);
for (const key of cutoutKeys) assert.ok(key in auto.params, `auto missing ${key}`);
assert.strictEqual(auto.params.sensitivity, 58);
assert.strictEqual(auto.params.texture_reduction, 35);
assert.strictEqual(auto.message, 'Принт извлечён в отдельный PNG');

console.log('R14_CLIENT_ROUTING_REGRESSION: 3/3 PASS');
