import { computed, ref } from 'vue';
import { useLatestResource } from './latestResource';

/** One in-flight request per action; errors remain visible until the next attempt. */
export function useAdminRequests() {
  const pending = ref(new Set<string>());
  const error = ref('');
  const busy = (key: string) => pending.value.has(key);
  async function run(key: string, action: () => Promise<unknown>) {
    if (busy(key)) return;
    pending.value.add(key);
    error.value = '';
    try { await action(); }
    catch (e) { error.value = e instanceof Error ? e.message : String(e); }
    finally { pending.value.delete(key); }
  }
  return { pending, error, busy, run };
}

export function useImportDestination<T extends { id: number }>(fetchOptions: (projectId: number) => Promise<T[]>) {
  const resource = useLatestResource<T[]>();
  const options = computed(() => resource.data.value ?? []);
  async function load(projectId: number | null) {
    if (projectId === null) { resource.clear(); return; }
    await resource.run(() => fetchOptions(projectId));
  }
  const valid = (id: number | null) => !resource.loading.value && !resource.error.value && options.value.some(item => item.id === id);
  return { options, loading: resource.loading, error: resource.error, load, valid };
}
