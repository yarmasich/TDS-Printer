<script setup lang="ts">
import { ref } from 'vue';
import { boundedNumber } from '@/data/numericInput';
import type { Template } from '@/api/types';
const props = defineProps<{ model: Omit<Template, 'id'> }>();
const units = ref('mm');
const linked = ref(false);
const step = () => units.value === 'mm' ? 0.1 : 1;
const positionKeys = ['gap_top','gap_bottom','gap_left','gap_right','left_offset','right_offset'] as const;
type PositionKey = typeof positionKeys[number];
const labels = ['Top inset','Bottom inset','Left inset','Right inset','Left vertical shift','Right vertical shift'];
function display(key: PositionKey) { return Number((props.model[key] * (units.value === 'mm' ? 25.4 / 300 : 1)).toFixed(3)); }
function position(key: PositionKey, e: Event) {
  const value = (e.target as HTMLInputElement).valueAsNumber;
  if (Number.isFinite(value)) props.model[key] = value * (units.value === 'mm' ? 300 / 25.4 : 1);
  (e.target as HTMLInputElement).value = String(display(key));
}
function size(side: 'left_pt'|'right_pt', value: number) {
  if (!Number.isFinite(value)) return;
  props.model[side] = Math.max(1, Math.min(72, value));
  if (linked.value) props.model.left_pt = props.model.right_pt = props.model[side];
}
function sizeInput(side: 'left_pt'|'right_pt', e: Event) {
  const input = e.target as HTMLInputElement;
  size(side, input.valueAsNumber);
  input.value = String(props.model[side]);
}
function spacingInput(key: 'min_font_pt' | 'letter_spacing_px' | 'line_spacing_px', e: Event) {
  const input = e.target as HTMLInputElement;
  if (key === 'line_spacing_px' && input.value === '') { props.model[key] = null; return; }
  const max = key === 'min_font_pt' ? Math.min(props.model.left_pt, props.model.right_pt) : key === 'letter_spacing_px' ? 20 : 100;
  props.model[key] = boundedNumber(input.valueAsNumber, props.model[key] ?? 0, key === 'min_font_pt' ? 1 : 0, max);
  input.value = String(props.model[key]);
}
function reset() { Object.assign(props.model, { font_name:'Microsoft Sans Serif',font_style:'Regular',left_pt:7,right_pt:7,h_align:'CENTER',v_align:'CENTER',scale_x:1,left_offset:0,right_offset:0,auto_fit:false,min_font_pt:4,letter_spacing_px:0,line_spacing_px:null }); }
</script>
<template>
  <section class="type-panel" aria-label="Typography">
    <header><strong>Typography</strong><button type="button" @click="reset" title="Reset font, sizes, alignment, stretch and vertical shifts">Reset</button></header>
    <label class="type-font">Font family<select v-model="model.font_name"><option>Microsoft Sans Serif</option><option>Calibri</option><option>PT Sans</option><option>PT Sans Narrow</option><option>IBM Plex Mono</option><option>Carlito</option><option>Cousine</option><option>PT Serif</option><option>IBM Plex Serif</option><option>B612 Mono</option></select></label>
    <div class="type-row" role="group" aria-label="Font style">
      <button v-for="style in (['Regular','Bold'] as const)" :key="style" type="button" :aria-pressed="model.font_style === style" @click="model.font_style = style">{{ style === 'Bold' ? 'B · Bold' : 'Regular' }}</button>
      <label class="type-link"><input type="checkbox" v-model="linked" @change="linked && (model.right_pt = model.left_pt)" /> Link sizes</label>
    </div>
    <div class="type-grid type-sizes">
      <label v-for="side in (['left_pt','right_pt'] as const)" :key="side">{{ side === 'left_pt' ? 'Left size · pt' : 'Right size · pt' }}
        <div class="type-stepper"><button type="button" :aria-label="`Decrease ${side}`" @click="size(side, model[side] - .5)">−</button><input type="number" min="1" max="72" step="0.5" :aria-label="side === 'left_pt' ? 'Left font size' : 'Right font size'" :value="model[side]" @change="sizeInput(side, $event)" /><button type="button" :aria-label="`Increase ${side}`" @click="size(side, model[side] + .5)">+</button></div>
      </label>
    </div>
    <div class="type-row type-presets" aria-label="Font size presets"><span>Both labels</span><button v-for="pt in [5,6,7,8,10,12]" :key="pt" type="button" @click="model.left_pt = model.right_pt = pt">{{ pt }}</button></div>
    <div class="type-grid">
      <label class="type-link"><input type="checkbox" v-model="model.auto_fit" /> Auto Fit</label>
      <label>Minimum size · pt<input type="number" :value="model.min_font_pt" @change="spacingInput('min_font_pt', $event)" min="1" :max="Math.min(model.left_pt, model.right_pt)" step="0.5" :disabled="!model.auto_fit" /></label>
    </div>
    <p v-if="model.auto_fit" class="type-help">Sizes above are maximums. Each label shrinks independently, down to the minimum. Text that still cannot fit is rejected.</p>
    <details class="type-spacing"><summary>Line & character spacing</summary>
      <div class="type-grid">
        <label>Character gap · px<input type="number" :value="model.letter_spacing_px" @change="spacingInput('letter_spacing_px', $event)" min="0" max="20" step="0.5" /></label>
        <label>Line gap · px<input type="number" :value="model.line_spacing_px ?? ''" min="0" max="100" step="0.5" placeholder="Auto" @change="spacingInput('line_spacing_px', $event)" /></label>
      </div>
      <p class="type-help">300 dpi design pixels. Blank line gap keeps automatic spacing; 0 adds no gap between line boxes. Character gap adds space without stretching glyphs.</p>
    </details>
    <div class="type-grid">
      <label>Horizontal<select v-model="model.h_align"><option value="LEFT">Left</option><option value="CENTER">Center</option><option value="RIGHT">Right</option></select></label>
      <label>Vertical<select v-model="model.v_align"><option value="TOP">Top</option><option value="CENTER">Middle</option><option value="BOTTOM">Bottom</option></select></label>
    </div>
    <label>Character width · {{ Math.round(model.scale_x * 100) }}%<input type="range" v-model.number="model.scale_x" min="1" max="1.5" step="0.01" aria-label="Character width" /></label>
    <details><summary>Position & spacing <select v-model="units" aria-label="Position units" @click.stop><option value="mm">mm</option><option value="px">px @ 300 dpi</option></select></summary>
      <div class="type-grid"><label v-for="(key, i) in positionKeys" :key="key">{{ labels[i] }}<input type="number" :aria-label="`${labels[i]} in ${units}`" :step="step()" :value="display(key)" @change="position(key, $event)" /></label></div>
    </details>
    <label class="type-link"><input type="checkbox" v-model="model.mirror_legend" /> Repeat text rotated 180° for wrap reading</label>
  </section>
</template>
<style scoped>
.type-panel { display:grid; gap:10px; font-size:12px; color:#334155; }
header,.type-row,summary { display:flex; gap:6px; align-items:center; } header { justify-content:space-between; } header strong { font-size:14px; }
.type-panel label { display:grid; gap:4px; font-size:11px; color:#64748b; }
.type-panel select,.type-panel input[type=number] { width:100%; min-width:0; padding:6px 8px; border:1px solid #cbd5e1; border-radius:5px; background:white; color:#334155; font-size:12px; }
.type-panel button { padding:5px 9px; border:1px solid #cbd5e1; border-radius:5px; background:white; color:#334155; cursor:pointer; font-size:12px; }
.type-panel button[aria-pressed=true] { background:#e0f2fe; border-color:#0284c7; color:#075985; }
.type-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; } .type-stepper { display:flex; gap:3px; } .type-stepper input { text-align:center; }
.type-panel .type-link { display:flex; align-items:center; gap:5px; } .type-presets span { font-size:10px; margin-right:6px; } .type-presets button { padding:4px 7px; }
summary { cursor:pointer; padding:8px 0; border-top:1px solid #e2e8f0; } summary select { width:auto!important; margin-left:auto; }
.type-panel :focus-visible { outline:2px solid #0284c7; outline-offset:2px; } input[type=range] { width:100%; accent-color:#0284c7; }
.type-sizes { grid-template-columns: repeat(2, 120px); gap:16px; }
.type-sizes .type-stepper { display:grid; grid-template-columns:26px minmax(0, 1fr) 26px; }
.type-sizes .type-stepper button { padding:4px; }
.type-sizes .type-stepper input { padding:4px; height:28px; appearance:textfield; -moz-appearance:textfield; }
.type-sizes input::-webkit-inner-spin-button, .type-sizes input::-webkit-outer-spin-button { -webkit-appearance:none; margin:0; }
.type-presets { flex-wrap:wrap; justify-content:flex-start; }
@media(max-width:360px) { .type-sizes { grid-template-columns:repeat(2,minmax(0,120px)); gap:8px; } }
.type-help { margin:0; font-size:10px; color:#64748b; line-height:1.5; }
</style>
