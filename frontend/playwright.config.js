import { defineConfig, devices } from "@playwright/test";

/* ADALET E2E — gerçek tarayıcı (gstack "real, not mocked").
   Kapsam: backend GEREKTİRMEYEN akışlar (giriş kapısı, misafir, hesap menüsü,
   sohbet geçmişi/localStorage). Üretim build'ine karşı (vite preview) koşar. */
const PORT = 4173;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "list" : [["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Build + preview'i Playwright başlatır (dist hazır olur).
  // env: VITE_E2E=1 → ?e2e=1 auth-bypass'ı (yalnız bu build'de) açar; gerçek prod set etmez.
  // Dummy VITE_SUPABASE_* → supabaseEnabled=true (AuthPage butonları aktif; gerçek ağ çağrısı yok).
  webServer: {
    command: `pnpm build && pnpm preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      VITE_E2E: "1",
      VITE_SUPABASE_URL: "https://e2e-placeholder.supabase.co",
      VITE_SUPABASE_ANON_KEY: "e2e-placeholder-anon-key",
    },
  },
});
