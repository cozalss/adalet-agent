import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ADALET web — geliştirmede backend'e (FastAPI :8000) proxy.
// /ask, /api, /me, /multimodal, /auth, /health, /metrics → backend.
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  // Vitest — jsdom ortamı (localStorage/atob/TextDecoder), saf mantık testleri.
  test: {
    environment: "jsdom",
    globals: true,
    css: false,
    include: ["src/**/*.test.{js,jsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "html"],
      // Kabuk/giriş-noktası ve demo verisi test edilebilir mantık değil → hariç.
      include: ["src/**/*.{js,jsx}"],
      exclude: ["src/**/*.test.{js,jsx}", "src/main.jsx", "src/lib/demoTurn.js"],
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/ask": { target: BACKEND, changeOrigin: true },
      "/api": { target: BACKEND, changeOrigin: true },
      // /me: tercih + sohbet geçmişi + dosya senkronu (auth'lu kullanıcı).
      "/me": { target: BACKEND, changeOrigin: true },
      "/multimodal": { target: BACKEND, changeOrigin: true },
      "/auth": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
      "/metrics": { target: BACKEND, changeOrigin: true },
    },
  },
});
