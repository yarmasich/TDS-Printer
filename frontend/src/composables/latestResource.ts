import { shallowRef, ref } from "vue";

/** Latest request owns the result, error and loading state. Clear also cancels ownership. */
export function useLatestResource<T>() {
  const data = shallowRef<T | null>(null);
  const loading = ref(false);
  const error = ref("");
  let revision = 0;
  function clear() {
    revision++;
    data.value = null;
    loading.value = false;
    error.value = "";
  }
  async function run(request: () => Promise<T>) {
    clear();
    const current = revision;
    loading.value = true;
    try {
      const result = await request();
      if (current === revision) data.value = result;
    } catch (failure) {
      if (current === revision) error.value = failure instanceof Error ? failure.message : String(failure);
    } finally {
      if (current === revision) loading.value = false;
    }
  }
  return { data, loading, error, clear, run };
}
