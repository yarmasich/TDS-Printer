<script setup lang="ts">
import StickyCart from "./StickyCart.vue";
defineProps<{ operator: string; reason: string; kiosk?: boolean }>();
</script>
<template><StickyCart :operator="operator" :reason="reason" :kiosk="kiosk" /></template>
