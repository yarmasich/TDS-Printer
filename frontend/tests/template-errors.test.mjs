import test from 'node:test';
import assert from 'node:assert/strict';
import { readApiError } from '../src/api/errors.ts';
import { pageSizeRepair } from '../src/data/templateGeometry.ts';
test('validation errors show messages without echoed input', async () => {
 const response = new Response(JSON.stringify({detail:[{loc:['body','template'],msg:'Value error, right text area must fit within the bitmap width',input:{name:'private'}}]}),{status:422});
 assert.equal(await readApiError(response), 'right text area must fit within the bitmap width');
});
test('non JSON error has readable fallback', async () => {
 assert.equal(await readApiError(new Response('<html>bad gateway</html>',{status:502})), 'Request failed (502).');
});
const legacy = {name:'R200X150',bytes_per_row:156,height:862,left_left:70,left_right:638,left_top:170,left_bottom:325,right_left:661,right_right:1261,right_top:170,right_bottom:325,gap_left:0,gap_right:0,gap_top:0,gap_bottom:0};
test('offers correct SKU page size without replacing calibrated rectangles', () => {
 assert.deepEqual(pageSizeRepair(legacy),{bytes_per_row:160,height:638});
 assert.equal(pageSizeRepair({...legacy,bytes_per_row:160,height:638}),null);
 assert.equal(pageSizeRepair({...legacy,right_right:2000}),null);
 assert.equal(pageSizeRepair({...legacy,name:'custom'}),null);
});
