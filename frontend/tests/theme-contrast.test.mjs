/**
 * Reads the real token values out of src/style.css and computes WCAG 2.1
 * contrast for every foreground/background pair the dark theme produces.
 * Parsing the stylesheet rather than restating the palette is the point: a
 * table that can drift from the CSS proves nothing.
 *
 * Scope is the DARK palette and the theme-invariant surfaces — the values this
 * theme introduced. Light mode is the untouched baseline and carries
 * pre-existing shortfalls (listed in the change's report), so asserting it
 * here would only need an allowlist.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

/** Tokens declared in one top-level rule, e.g. `:root` or `.tds-dark`. */
function tokens(selector) {
  const start = css.indexOf(selector + ' {');
  assert.notEqual(start, -1, `${selector} block missing from style.css`);
  const body = css.slice(start, css.indexOf('\n}', start));
  const found = {};
  for (const [, name, value] of body.matchAll(/--tds-([\w-]+):\s*(#[0-9a-fA-F]{3,8});/g)) {
    found[name] = value;
  }
  return found;
}

const LIGHT = tokens(':root');
const DARK = {...LIGHT, ...tokens('.tds-dark')};   // dark overrides a light base

const luminance = (hex) => {
  let h = hex.slice(1);
  if (h.length === 3) h = [...h].map(c => c + c).join('');
  const [r, g, b] = [0, 2, 4]
    .map(i => parseInt(h.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const BODY = 4.5;   // SC 1.4.3 body text
const UI = 3;       // SC 1.4.11 informational boundary / state indicator

/** [foreground token, background token, threshold, what it paints] */
const DARK_PAIRS = [
  ['ink', 'surface', BODY, 'primary text on a card'],
  ['ink', 'sunken', BODY, 'primary text on the page'],
  ['ink', 'muted', BODY, 'primary text on a chip'],
  ['ink', 'surface-hover', BODY, 'primary text on a hovered row'],
  ['ink-2', 'surface', BODY, 'body text on a card'],
  ['ink-2', 'sunken', BODY, 'body text on the page'],
  ['ink-2', 'muted', BODY, 'body text on a chip'],
  ['ink-2', 'surface-hover', BODY, 'body text on a hovered row'],
  ['ink-3', 'surface', BODY, 'muted caption on a card'],
  ['ink-3', 'sunken', BODY, 'muted caption on the page'],
  ['ink-3', 'muted', BODY, 'muted caption on a chip'],
  ['ink-4', 'surface', BODY, 'faint metadata on a card'],
  ['ink-4', 'sunken', BODY, 'faint metadata on the page'],
  ['ink-4', 'muted', UI, 'hovered control border'],
  ['edge-strong', 'surface', UI, 'native control border on a card'],
  ['edge-strong', 'sunken', UI, 'native control border on the page'],
  ['edge-strong', 'muted', UI, 'off-state indicator dot'],
  ['accent', 'surface', BODY, 'link or icon on a card'],
  ['accent', 'sunken', BODY, 'link or icon on the page'],
  ['accent-ink', 'surface', BODY, 'disclosure link on a card'],
  ['accent-ink', 'sunken', BODY, 'in-progress status on a cart row'],
  ['accent-ink', 'accent-soft', BODY, 'text on an accent tint'],
  ['accent-ink', 'accent-soft-hover', BODY, 'text on a hovered accent tint'],
  ['accent-solid-ink', 'accent-solid', BODY, 'cart count pill'],
  ['accent-edge', 'surface', UI, 'accent control border on a card'],
  ['danger', 'surface', BODY, 'error text on a card'],
  ['danger', 'sunken', BODY, 'error text on the page'],
  ['danger', 'danger-soft', BODY, 'error text on an error tint'],
  ['danger-edge', 'surface', UI, 'error control border on a card'],
  ['warn', 'surface', BODY, 'warning text on a card'],
  ['warn', 'sunken', BODY, 'warning text on the page'],
  ['warn', 'warn-soft', BODY, 'warning text on a warning tint'],
  ['warn-edge', 'surface', UI, 'warning control border on a card'],
  ['ok', 'surface', BODY, 'success text on a card'],
  ['ok', 'ok-soft', BODY, 'success text on a success tint'],
  ['ok-solid', 'surface', UI, 'on-state indicator dot'],
  ['badge', 'badge-soft', BODY, 'protocol badge text on its tint'],
];

/** Same hex in both themes, so one check covers them. */
const INVARIANT_PAIRS = [
  ['stage-ink', 'stage', BODY, 'inherited text on the workspace light table'],
  ['stage-ink', 'stage-sheet', BODY, 'annotation on white label stock'],
  ['stage-ink', 'stage-sunken', BODY, 'label text fallback on the sticker stage'],
  ['stage-ink', 'stage-muted', BODY, 'inherited text on the QR preview'],
  ['stage-ink-2', 'stage', BODY, 'SVG area labels on the light table'],
  ['stage-ink-2', 'stage-muted', BODY, 'QR preview caption'],
  ['stage-accent-ink', 'stage-sunken', BODY, 'matched-side caption on the sticker stage'],
  ['stage-accent', 'stage', UI, 'dashed print-area guide on the light table'],
  ['stage-accent', 'stage-sheet', UI, 'dashed print-area guide on label stock'],
  ['chrome-ink', 'chrome', BODY, 'header text on the chrome bar'],
  ['chrome-ink', 'chrome-to', BODY, 'header text at the chrome gradient end'],
  ['chrome-warn', 'chrome', BODY, 'printer warning on the kiosk bar'],
];

function check(palette, pairs, label) {
  const failures = [];
  for (const [fg, bg, need, what] of pairs) {
    assert.ok(palette[fg], `--tds-${fg} is not declared`);
    assert.ok(palette[bg], `--tds-${bg} is not declared`);
    const ratio = contrast(palette[fg], palette[bg]);
    if (ratio < need) {
      failures.push(
        `${what}: --tds-${fg} (${palette[fg]}) on --tds-${bg} (${palette[bg]}) ` +
        `= ${ratio.toFixed(2)}:1, needs ${need}:1`,
      );
    }
  }
  assert.deepEqual(failures, [], `${label}\n  ` + failures.join('\n  '));
}

test('the dark palette clears WCAG AA for every pair it paints', () => {
  check(DARK, DARK_PAIRS, 'dark theme contrast failures');
});

test('the label light table and dark chrome clear AA in both themes', () => {
  check(LIGHT, INVARIANT_PAIRS, 'invariant surfaces, light theme');
  check(DARK, INVARIANT_PAIRS, 'invariant surfaces, dark theme');
  for (const [fg, bg] of INVARIANT_PAIRS) {
    assert.equal(LIGHT[fg], DARK[fg], `--tds-${fg} must not flip with the theme`);
    assert.equal(LIGHT[bg], DARK[bg], `--tds-${bg} must not flip with the theme`);
  }
});

test('a label light table always stands clear of the card it sits on', () => {
  // The white stock must read as an object on the page, not as the page.
  assert.ok(contrast(DARK['stage'], DARK['surface']) >= UI);
});
