import test from 'node:test';
import assert from 'node:assert/strict';
import { labelStock, labelStockForPreview } from '../src/data/labelStock.ts';

const px = (mm) => mm * 300 / 25.4;

// Values as shipped in server/app/data/materials.json (EasyMark 2.0.0.229).
const S200X400VATY = {
  sku: 'S200X400VATY', rows: 1, columns: 2, page_width_mm: 107.95, page_height_mm: 104.775,
  left_margin_mm: 3.175, top_margin_mm: 1.6002, print_width_mm: 50.8, print_height_mm: 25.4,
  column_pitch_mm: 50.8, label_width_mm: 50.8, label_length_mm: 101.6, print_on_height_mm: 25.4,
  label_kind: 'Self-Laminating', corner_radius_mm: 1.5748,
};
const R200X150V1T = {
  sku: 'R200X150V1T', rows: 1, columns: 2, page_width_mm: 107.95, page_height_mm: 53.975,
  left_margin_mm: 3.175, top_margin_mm: 14.3002, print_width_mm: 50.8, print_height_mm: 12.7,
  column_pitch_mm: 50.8, label_width_mm: 50.8, label_length_mm: 38.1, print_on_height_mm: 12.7,
  label_kind: 'Turn-Tell', corner_radius_mm: 0,
};

// "Apply full layout": text areas exactly on the print-on areas.
function fullLayout(m, overrides = {}) {
  const top = px(m.top_margin_mm), bottom = px(m.top_margin_mm + m.print_height_mm);
  return {
    name: m.sku, material_sku: m.sku, bytes_per_row: 160, height: Math.round(px(m.page_height_mm)),
    left_left: px(m.left_margin_mm), left_right: px(m.left_margin_mm + m.print_width_mm),
    right_left: px(m.left_margin_mm + m.column_pitch_mm), right_right: px(m.left_margin_mm + m.column_pitch_mm + m.print_width_mm),
    left_top: top, left_bottom: bottom, right_top: top, right_bottom: bottom,
    gap_top: 0, gap_bottom: 0, gap_left: 0, gap_right: 0, ...overrides,
  };
}
const close = (a, b) => assert.ok(Math.abs(a - b) < 0.01, `${a} ≉ ${b}`);

test('a self-laminating label is its full 2" × 4" die cut with the white area at its top', () => {
  const stock = labelStock(S200X400VATY, fullLayout(S200X400VATY));
  assert.equal(stock.labels.length, 2);
  const [left] = stock.labels;
  close(left.outline.w, px(50.8)); close(left.outline.h, px(101.6)); close(left.outline.y, 0);
  close(left.printOn.y, px(1.6002)); close(left.printOn.h, px(25.4));
  assert.equal(left.clear, true);
  close(left.radius, px(1.5748));
  assert.equal(stock.kind, 'Self-Laminating');
  assert.deepEqual(stock.warnings, []);
});

test('text areas below the white area are reported in millimetres', () => {
  // The reported template: areas kept from R200x150 at 168.9 px (14.3 mm).
  const stock = labelStock(S200X400VATY, fullLayout(S200X400VATY, {
    left_top: 168.9, left_bottom: 468.9, right_top: 168.9, right_bottom: 468.9,
  }));
  assert.equal(stock.warnings.length, 2);
  assert.match(stock.warnings[0], /^Left label: text area is 12\.7 mm outside the white print-on area\.$/);
  assert.match(stock.warnings[1], /^Right label/);
});

test('a small calibration nudge is not reported', () => {
  const t = fullLayout(S200X400VATY);
  const stock = labelStock(S200X400VATY, { ...t, left_top: t.left_top + px(0.5), left_bottom: t.left_bottom + px(0.5) });
  assert.deepEqual(stock.warnings, []);
});

test('Turn-Tell keeps its 2" × 1.5" shape and the preview\'s mirrored columns', () => {
  const t = fullLayout(R200X150V1T);
  const [left] = labelStock(R200X150V1T, t).labels;
  close(left.outline.h, px(38.1));  // EasyMark's prose says 2.250", which cannot fit its 2.125" row
  // The preview is rotated 180°: the operator-left label is the right column, mirrored.
  close(left.printOn.x, t.bytes_per_row * 8 - t.right_right);
  assert.deepEqual(labelStock(R200X150V1T, t).warnings, []);
});

test('a label without a print-on height is opaque all over', () => {
  const plain = { ...S200X400VATY, print_on_height_mm: null, label_kind: 'Component' };
  assert.equal(labelStock(plain, fullLayout(plain)).labels[0].clear, false);
});

test('without a trustworthy shape there is no label view', () => {
  const t = fullLayout(S200X400VATY);
  assert.equal(labelStock({ ...S200X400VATY, label_width_mm: null }, t), null);
  assert.equal(labelStock({ ...S200X400VATY, columns: 4 }, t), null);
  // A print area outside its own label means the description was misread.
  assert.equal(labelStock({ ...S200X400VATY, label_length_mm: 10 }, t), null);
  assert.equal(labelStock(null, t), null);
});


// The operator card gets areas from /api/labels/{id}/preview, already mirrored
// for Turn-Tell the way previewAreas mirrors them, plus the catalog stock.
function operatorPreview(m, t) {
  const width = t.bytes_per_row * 8;
  const turn = /^(R150X150|R200X150)/i.test(m.sku);
  const areas = ['Left', 'Right'].map((label, i) => {
    const side = turn ? (i === 0 ? 'right' : 'left') : label.toLowerCase();
    const x0 = t[`${side}_left`], x1 = t[`${side}_right`];
    return { label, x: turn ? width - x1 : x0, y: t[`${side}_top`], width: x1 - x0, height: t[`${side}_bottom`] - t[`${side}_top`] };
  });
  return { material_sku: m.sku, width, height: t.height, areas, stock: m };
}

test('the operator card draws the same physical labels as the editor', () => {
  const t = fullLayout(S200X400VATY);
  const card = labelStockForPreview(operatorPreview(S200X400VATY, t));
  const editor = labelStock(S200X400VATY, t);
  assert.deepEqual(card.labels.map((l) => [l.outline, l.printOn]), editor.labels.map((l) => [l.outline, l.printOn]));
  assert.deepEqual(card.warnings, []);
});

test('the operator card shows a misplaced template as misplaced', () => {
  const t = fullLayout(S200X400VATY, { left_top: 168.9, left_bottom: 468.9, right_top: 168.9, right_bottom: 468.9 });
  assert.equal(labelStockForPreview(operatorPreview(S200X400VATY, t)).warnings.length, 2);
});

test('the operator card mirrors Turn-Tell columns like its preview image', () => {
  const t = fullLayout(R200X150V1T);
  const [left] = labelStockForPreview(operatorPreview(R200X150V1T, t)).labels;
  close(left.printOn.x, t.bytes_per_row * 8 - t.right_right);
  close(left.outline.h, px(38.1));
});

test('a card without catalog stock has no label view', () => {
  const t = fullLayout(S200X400VATY);
  assert.equal(labelStockForPreview({ ...operatorPreview(S200X400VATY, t), stock: null }), null);
});
