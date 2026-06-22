import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// ADALET web — geliştirmede backend'e (FastAPI :8000) proxy.
// /ask, /api, /me, /multimodal, /auth, /health, /metrics → backend.
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // shadcn bileşenleri "@/..." ile import eder → @ = src.
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // Build hedefi es2022: esbuild 0.28+ (güvenlik yaması) varsayılan es2020 hedefine
  // destructuring down-level'i "desteklenmiyor" diye reddediyor. Modern tarayıcılar
  // (2022+: Chrome 94+/FF 93+/Safari 15.4+) es2022'yi native destekler → transform gerekmez.
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("react") || id.includes("scheduler")) return "react-vendor";
          if (id.includes("@supabase")) return "supabase-vendor";
          return "vendor";
        },
      },
    },
  },
  // Dev-server dep pre-bundling (esbuild) AYRI target kullanır → onu da es2022 yap
  // (yoksa dev'de supabase-js destructuring aynı esbuild 0.28 hatasını verir).
  optimizeDeps: { esbuildOptions: { target: "es2022" } },
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
      // /emsal: "İlgili Kararlar" tam-metin (on-demand). Public yargi-mcp yavaş (~20s) →
      // proxyTimeout yükseltilir, yoksa proxy isteği erken keser ("getirilemedi" hatası).
      "/emsal": { target: BACKEND, changeOrigin: true, proxyTimeout: 60000, timeout: 60000 },
      "/feedback": { target: BACKEND, changeOrigin: true },
      "/auth": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
      "/metrics": { target: BACKEND, changeOrigin: true },
    },
  },
});
