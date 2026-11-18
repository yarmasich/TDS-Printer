<script setup lang="ts">
import { computed, useId } from 'vue';
import type { LabelPreview } from '@/data/labelPreview';
import { labelStockForPreview } from '@/data/labelStock';
const props = defineProps<{ preview: LabelPreview; side: 'Left' | 'Right' }>();
const id = `sticker-${useId().replace(/:/g, '')}`;
const area = computed(() => props.preview.areas.find(area => area.label === props.side));
// The die-cut label from the Panduit catalog, drawn exactly like the template
// editor: ink lands where it prints, so text off the white area shows on film.
const label = computed(() => labelStockForPreview(props.preview)?.labels.find(l => l.label === props.side) ?? null);
// Without catalog stock only the text area can be shown.
const box = computed(() => label.value ? label.value.outline
  : area.value ? { x: area.value.x, y: area.value.y, w: area.value.width, h: area.value.height } : null);
</script>

<template>
  <svg v-if="box" class="sticker" :viewBox="`0 0 ${box.w} ${box.h}`" role="img" :aria-label="`${side} printed label${label?.clear ? ' with clear film' : label ? '' : ' text area'}`">
    <defs>
      <pattern :id="`${id}-film`" width="18" height="18" patternUnits="userSpaceOnUse">
        <rect width="18" height="18" fill="#f5f8fa" />
        <path d="M0 0h9v9H0zM9 9h9v9H9z" fill="#e4ecf1" />
      </pattern>
      <clipPath :id="`${id}-edge`"><rect :width="box.w" :height="box.h" :rx="label ? label.radius : 9" /></clipPath>
    </defs>
    <g :clip-path="`url(#${id}-edge)`">
      <rect :width="box.w" :height="box.h" :fill="label?.clear ? `url(#${id}-film)` : 'white'" />
      <rect v-if="label" :x="label.printOn.x - box.x" :y="label.printOn.y - box.y" :width="label.printOn.w" :height="label.printOn.h" :fill="preview.material?.color || 'white'" />
      <!-- Multiply keeps the bitmap's white background from painting over the film. -->
      <svg x="0" y="0" :width="box.w" :height="box.h" :viewBox="`${box.x} ${box.y} ${box.w} ${box.h}`" overflow="hidden">
        <image :href="preview.image" x="0" y="0" :width="preview.width" :height="preview.height" preserveAspectRatio="none" style="mix-blend-mode:multiply" />
      </svg>
    </g>
    <rect x=".75" y=".75" :width="box.w - 1.5" :height="box.h - 1.5" :rx="label ? label.radius : 9" fill="none" stroke="#b4c5d0" stroke-width="1" vector-effect="non-scaling-stroke" />
  </svg>
</template>

<style scoped>
/* max-height keeps a 2" × 4" self-laminating label from making each result row
   half a screen tall; the viewBox keeps its proportions inside the box. */
.sticker { display:block; width:100%; max-width:260px; max-height:240px; margin:auto; filter:drop-shadow(0 3px 3px #33415515); }
</style>
