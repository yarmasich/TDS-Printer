/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of the FastAPI backend. Leave empty for same-origin (dev via
   * Vite proxy, or prod behind a reverse proxy that forwards `/api`).
   * Example: `VITE_API_BASE_URL=http://10.0.0.5:8000`.
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
