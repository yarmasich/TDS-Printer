<script setup lang="ts">
import PrintersSection from "@/components/admin/PrintersSection.vue";
import TemplatesSection from "@/components/admin/TemplatesSection.vue";
import ProjectsTree from "@/components/admin/ProjectsTree.vue";
import ImportsSection from "@/components/admin/ImportsSection.vue";
import ListsSection from "@/components/admin/ListsSection.vue";
import HistorySection from "@/components/admin/HistorySection.vue";
</script>

<template>
  <div class="space-y-4">
    <PrintersSection />
    <TemplatesSection />
    <ProjectsTree />
    <ImportsSection />
    <ListsSection />
    <HistorySection />
  </div>
</template>
