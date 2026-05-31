import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ADALET web — geliştirmede backend'e (FastAPI :8000) proxy.
// /ask, /api, /multimodal, /auth, /health, /metrics → backend.
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ask": { target: BACKEND, changeOrigin: true },
      "/api": { target: BACKEND, changeOrigin: true },
      "/multimodal": { target: BACKEND, changeOrigin: true },
      "/auth": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
      "/metrics": { target: BACKEND, changeOrigin: true },
    },
  },
});
