import { computed, ref } from "vue";
import type { PrintPolicy } from "@/api/types";

/** One policy check and one card per batch. Card data lives only in memory. */
export function useRfidPrint(
  getPolicy: () => Promise<PrintPolicy>,
  print: (code?: string) => Promise<void>,
) {
  const open = ref(false);
  const code = ref("");
  const error = ref("");
  const checking = ref(false);
  const submitting = ref(false);
  const ready = ref(false);
  const busy = computed(() => checking.value || submitting.value);

  async function execute(card?: string) {
    submitting.value = true;
    code.value = "";
    error.value = "";
    try {
      await print(card);
      open.value = false;
      ready.value = false;
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      code.value = "";
      submitting.value = false;
    }
  }

  async function start() {
    if (busy.value || open.value) return;
    checking.value = true;
    ready.value = false;
    code.value = "";
    error.value = "";
    try {
      const policy = await getPolicy();
      if (policy.requires_rfid) {
        open.value = true;
        ready.value = policy.configured;
        if (!policy.configured) error.value = "RFID integration is not configured. Contact an administrator before printing.";
      } else {
        await execute();
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      checking.value = false;
    }
  }

  async function submit() {
    if (!open.value || !ready.value || busy.value || !code.value.trim()) return;
    await execute(code.value);
  }

  function close() {
    if (busy.value) return;
    open.value = false;
    code.value = "";
    error.value = "";
    ready.value = false;
  }

  return { open, code, error, checking, submitting, ready, busy, start, submit, close };
}
