import test from 'node:test';
import assert from 'node:assert/strict';
import { previewAreas } from '../src/data/previewGeometry.ts';
const t = { name:'custom', material_sku:'', bytes_per_row:160, height:700,
  left_left:20,left_right:600,left_top:100,left_bottom:250,
  right_left:660,right_right:1240,right_top:110,right_bottom:260,
  gap_left:5,gap_right:10,gap_top:3,gap_bottom:7 };
test('normal raster guides respect asymmetric insets', () => {
  assert.deepEqual(previewAreas(t)[0],{label:'Left label',x:25,y:103,width:565,height:140});
});
test('Turn-Tell guides match rotated server preview and swapped columns', () => {
  assert.deepEqual(previewAreas({...t,material_sku:'R200X150V1T'})[0],{label:'Left label',x:50,y:113,width:565,height:140});
});
test('explicit non Turn-Tell SKU overrides a legacy template name and dimensions', () => {
  assert.equal(previewAreas({...t,name:'R200X150',height:638,material_sku:'S200X400'})[0].x,25);
});
test('legacy Turn-Tell dimensions use operator orientation', () => {
  assert.equal(previewAreas({...t,height:638})[0].x,50);
});
