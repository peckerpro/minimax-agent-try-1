import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build the React app directly into the FastAPI static dir so the
// backend can serve it without any post-build copy step.
//
// `base: "./"` makes Vite emit relative asset paths (./assets/...)
// so the SPA works when mounted under FastAPI's `StaticFiles(html=True)`
// at any URL prefix.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../hello_agent/web/static",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8648",
        changeOrigin: true,
      },
    },
  },
});