import test from 'node:test';
import assert from 'node:assert/strict';
import { brandForModel, modelsForBrand, settingsForModel, isValidPrinterSelection, changePrinterBrand } from '../src/data/printerModels.ts';

test('reselecting the same brand preserves manual settings and selected known models',()=>{
 for(const selection of [
  {brand:'custom',model:'custom',protocol:'jscript',dpi:203},
  {brand:'panduit',model:'DP4600H',protocol:'jscript',dpi:600},
  {brand:'brother',model:'QL-1110NWBc',protocol:'brother_ql',dpi:300},
 ]) assert.deepEqual(changePrinterBrand(selection,selection.brand),selection);
});

test('only a real brand switch clears incompatible model and manual settings',()=>{
 const original={brand:'custom',model:'custom',protocol:'jscript',dpi:203};
 assert.deepEqual(changePrinterBrand(original,'brother'),{brand:'brother',model:null,protocol:'epl2',dpi:300});
 assert.deepEqual(changePrinterBrand(original,'panduit'),{brand:'panduit',model:null,protocol:'epl2',dpi:300});
 assert.deepEqual(original,{brand:'custom',model:'custom',protocol:'jscript',dpi:203});
});

test('brand restricts available models and rejects cross-brand selections',()=>{
 assert.deepEqual(modelsForBrand(null),[]);
 assert.deepEqual(modelsForBrand('brother').map(p=>p.value),['QL-1110NWBc']);
 assert.deepEqual(modelsForBrand('panduit').map(p=>p.value),['DP4300M','DP4300H','DP4600H','DP4300HD','TDP43ME']);
 assert.deepEqual(modelsForBrand('custom').map(p=>p.value),['custom']);
 assert.equal(isValidPrinterSelection(null,null,'epl2',300),false);
 assert.equal(isValidPrinterSelection('brother',null,'epl2',300),false);
 assert.equal(isValidPrinterSelection('panduit','QL-1110NWBc','brother_ql',300),false);
 assert.equal(isValidPrinterSelection('brother','DP4300H','jscript',300),false);
 assert.equal(isValidPrinterSelection('brother','QL-1110NWBc','brother_ql',300),true);
});

test('every known model has the backend native protocol and resolution',()=>{
 const expected={DP4300M:['panduit','jscript',300],DP4300H:['panduit','jscript',300],DP4600H:['panduit','jscript',600],DP4300HD:['panduit','jscript',300],TDP43ME:['panduit','ezpl',300],'QL-1110NWBc':['brother','brother_ql',300]};
 for(const [model,[brand,protocol,dpi]] of Object.entries(expected)){
  assert.equal(brandForModel(model),brand);
  assert.deepEqual(settingsForModel(model,{protocol:'epl2',dpi:203}),{model,protocol,dpi});
 }
});

test('legacy custom edits preserve manual settings and send no UI brand field',()=>{
 for(const protocol of ['epl2','ezpl','jscript']){
  assert.equal(brandForModel('custom'),'custom');
  assert.equal(brandForModel(undefined),'custom');
  assert.deepEqual(settingsForModel('custom',{protocol,dpi:203}),{model:'custom',protocol,dpi:203});
  assert.equal(isValidPrinterSelection('custom','custom',protocol,203),true);
 }
 assert.equal(isValidPrinterSelection('custom','custom','brother_ql',300),false);
 assert.equal(isValidPrinterSelection('custom','custom','jscript',123),false);
});

test('known model display/save settings normalize stale metadata without mutating a saved row',()=>{
 const saved={model:'DP4600H',protocol:'epl2',dpi:300};
 const settings=settingsForModel(saved.model,saved);
 assert.deepEqual(settings,{model:'DP4600H',protocol:'jscript',dpi:600});
 assert.deepEqual(saved,{model:'DP4600H',protocol:'epl2',dpi:300});
 assert.equal(Object.hasOwn(settings,'brand'),false);
});

test('an unrecognised model renders with its stored settings instead of throwing',()=>{
 assert.deepEqual(settingsForModel('DP9000X',{protocol:'jscript',dpi:600}),{model:'DP9000X',protocol:'jscript',dpi:600});
 assert.deepEqual(settingsForModel(undefined,{protocol:'epl2',dpi:203}),{model:undefined,protocol:'epl2',dpi:203});
 assert.equal(isValidPrinterSelection('panduit','DP9000X','jscript',600),false);
});
