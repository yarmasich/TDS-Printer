/** Read FastAPI errors without exposing request payloads or proxy HTML. */
export async function readApiError(response: Response): Promise<string> {
  const fallback = `Request failed (${response.status}).`;
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail)) {
      const messages = data.detail.flatMap((issue: { msg?: unknown; loc?: unknown }) => {
        if (typeof issue?.msg !== 'string') return [];
        const field = Array.isArray(issue.loc)
          ? issue.loc.filter((part: unknown) => part !== 'body' && part !== 'template').join('.')
          : '';
        return [`${field ? field + ': ' : ''}${issue.msg.replace(/^Value error, /, '')}`];
      });
      if (messages.length) return [...new Set(messages)].join('; ');
    } else if (data?.detail && typeof data.detail === 'object') {
      // Structured details carry the operator-facing reason in `message`; the
      // other fields are codes and echoes, so only `message` is rendered.
      const message = (data.detail as { message?: unknown }).message;
      if (typeof message === 'string' && message.trim()) return message;
    }
  } catch { /* Non-JSON errors use the HTTP status. */ }
  return fallback;
}
