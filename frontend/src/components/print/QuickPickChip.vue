<script setup lang="ts" generic="T">
/**
 * Compact chip that opens a popover with a list of options.
 *
 * "Empty" state: shows a placeholder + dashed border.
 * "Set" state: shows the value + a × clear button.
 */
import { ref } from "vue";
import Popover from "primevue/popover";
import Listbox from "primevue/listbox";

const props = defineProps<{
  label: string;
  modelValue: string;
  options: T[];
  optionLabel: keyof T;
  /** the option field that maps to a plain string we store as modelValue */
  optionValue: keyof T;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const popoverRef = ref<InstanceType<typeof Popover> | null>(null);

function open(event: MouseEvent) {
  popoverRef.value?.show(event);
}

function pick(opt: T) {
  emit("update:modelValue", String(opt[props.optionValue]));
  popoverRef.value?.hide();
}

function clear(e: Event) {
  e.stopPropagation();
  emit("update:modelValue", "");
}
</script>

<template>
  <button
    type="button"
    class="chip"
    :class="{ 'chip-set': modelValue }"
    @click="open"
  >
    <span class="chip-label">{{ label }}</span>
    <span v-if="modelValue" class="chip-value">{{ modelValue }}</span>
    <span v-else class="chip-placeholder">— set —</span>
    <button
      v-if="modelValue"
      type="button"
      class="chip-clear"
      aria-label="Clear"
      @click="clear"
    >
      ×
    </button>
  </button>
  <Popover ref="popoverRef" :style="{ width: '20rem' }">
    <Listbox
      :model-value="modelValue"
      :options="options"
      :option-label="optionLabel as string"
      :option-value="optionValue as string"
      :filter="options.length > 8"
      list-style="max-height: 16rem"
      @update:model-value="(v: unknown) => pick(options.find(o => String(o[optionValue]) === String(v)) as T)"
    />
  </Popover>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1.5px dashed #cbd5e1;
  background: #f8fafc;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover {
  border-color: #0284c7;
  background: #f0f9ff;
}
.chip.chip-set {
  border-style: solid;
  border-color: #0284c7;
  background: #f0f9ff;
}
.chip-label {
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.5px;
}
.chip-set .chip-label {
  color: #0369a1;
}
.chip-value {
  color: #0f172a;
  font-weight: 600;
}
.chip-placeholder {
  color: #94a3b8;
}
.chip-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(2, 132, 199, 0.15);
  border: 0;
  color: #075985;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
}
.chip-clear:hover {
  background: rgba(2, 132, 199, 0.3);
}
</style>
