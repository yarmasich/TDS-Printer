import { defineConfig, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8000";

/** Drop broken ``./fonts/`` urls; we ship fonts from ``public/fonts`` instead. */
function stripPrimeiconsFontFace(): Plugin {
  return {
    name: "strip-primeicons-font-face",
    enforce: "pre",
    transform(code, id) {
      if (!id.endsWith("primeicons/primeicons.css")) return;
      return code.replace(/@font-face\s*\{[\s\S]*?\}\s*/m, "");
    },
  };
}

const proxy = {
  "/api": { target: API_TARGET, changeOrigin: true },
};

export default defineConfig({
  plugins: [vue(), stripPrimeiconsFontFace()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
});
