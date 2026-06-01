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
  webServer: {
    command: `pnpm build && pnpm preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
