<script setup lang="ts">
import { computed, useId } from 'vue';
import { stickerGeometry, type LabelPreview } from '@/data/labelPreview';
const props = defineProps<{ preview: LabelPreview; side: 'Left' | 'Right' }>();
const id = `sticker-${useId().replace(/:/g, '')}`;
const area = computed(() => props.preview.areas.find(area => area.label === props.side));
const shape = computed(() => area.value ? stickerGeometry(props.preview, area.value) : null);
</script>

<template>
  <svg v-if="area && shape" class="sticker" :viewBox="`0 0 ${shape.width} ${shape.height}`" role="img" :aria-label="`${side} printed label${preview.material ? ' with transparent wrap' : ' text area'}`">
    <defs>
      <pattern :id="`${id}-film`" width="18" height="18" patternUnits="userSpaceOnUse">
        <rect width="18" height="18" fill="#f5f8fa" />
        <path d="M0 0h9v9H0zM9 9h9v9H9z" fill="#e4ecf1" />
      </pattern>
      <clipPath :id="`${id}-edge`"><rect :width="shape.width" :height="shape.height" rx="9" /></clipPath>
    </defs>
    <g :clip-path="`url(#${id}-edge)`">
      <rect :width="shape.width" :height="shape.height" :fill="preview.material ? `url(#${id}-film)` : 'white'" />
      <rect :y="shape.top" :width="shape.width" :height="shape.band" :fill="preview.material?.color || 'white'" />
      <svg x="0" :y="shape.top" :width="shape.width" :height="shape.band" :viewBox="`${area.x} ${area.y} ${shape.width} ${shape.band}`" overflow="hidden">
        <image :href="preview.image" x="0" y="0" :width="preview.width" :height="preview.height" preserveAspectRatio="none" style="mix-blend-mode:multiply" />
      </svg>
    </g>
    <rect x=".75" y=".75" :width="shape.width - 1.5" :height="shape.height - 1.5" rx="9" fill="none" stroke="#b4c5d0" stroke-width="1" vector-effect="non-scaling-stroke" />
  </svg>
</template>

<style scoped>
.sticker { display:block; width:100%; max-width:260px; margin:auto; filter:drop-shadow(0 3px 3px #33415515); }
</style>
