import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8000";

// Same proxy used in `npm run dev` and `npm run preview` so the SPA can
// always call relative ``/api/*`` regardless of where it's served from.
const proxy = {
  "/api": { target: API_TARGET, changeOrigin: true },
};

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
});
