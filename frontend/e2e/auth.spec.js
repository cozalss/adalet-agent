import { test, expect } from "@playwright/test";

/* Giriş kapısı (backend gerektirmez). Misafir modu KALDIRILDI → uygulamaya giriş
   E2E'de ?e2e=1 ile (VITE_E2E build flag'i; gerçek prod'da kapalı). */
test.describe("Giriş kapısı", () => {
  test("token yokken AuthPage gösterilir (Giriş + Kayıt sekmeleri)", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("tab", { name: "Giriş" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Kayıt ol" })).toBeVisible();
    await expect(page.getByText("Tekrar hoş geldiniz")).toBeVisible();
    await expect(page.getByText("doğrulanmış")).toBeVisible(); // marka tagline
  });

  test("Kayıt ol sekmesi ad + gizlilik onayı alanlarını gösterir", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: "Kayıt ol" }).click();
    await expect(page.getByRole("heading", { name: "Hesap oluşturun" })).toBeVisible();
    await expect(page.getByRole("checkbox")).toBeVisible(); // KVKK onayı
  });

  test("boş giriş → doğrulama hatası", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Giriş yap" }).click();
    await expect(page.getByRole("alert")).toContainText("E-posta ve şifre gerekli");
  });

  test("misafir seçeneği YOK (kayıt/giriş zorunlu)", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Misafir olarak devam et" })).toHaveCount(0);
  });

  test("?e2e=1 auth'u atlar → /sor sohbet uygulaması", async ({ page }) => {
    await page.goto("/?e2e=1");
    await expect(page.locator(".sor-app")).toBeVisible();
    await expect(page.getByRole("heading", { name: /yardımcı olabilirim/i })).toBeVisible();
  });
});
