import { test, expect } from "@playwright/test";

/* Hesap menüsü — ADALET'e özgü öğeler + kapsam modalı (misafir, backend'siz). */
test.describe("Hesap menüsü", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("adalet-guest", "1"));
    await page.goto("/");
  });

  test("pill → menü ADALET öğeleriyle açılır", async ({ page }) => {
    await page.getByRole("button", { name: "Hesap menüsünü aç" }).click();
    await expect(page.getByRole("menuitem", { name: /ADALET nasıl çalışır/ })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: /Erişilebilirlik & tercihler/ })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: /Açık kaynak/ })).toBeVisible();
  });

  test("Hangi konularda → kapsam modalı (alanlar + ceza kapsam-dışı)", async ({ page }) => {
    await page.getByRole("button", { name: "Hesap menüsünü aç" }).click();
    await page.getByRole("menuitem", { name: /Hangi konularda/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Bilerek kapsam dışı")).toBeVisible();
    await expect(dialog.getByText("Ceza hukuku")).toBeVisible();
  });

  test("Erişilebilirlik & tercihler → yazı boyutu uygulanır (zoom)", async ({ page }) => {
    await page.getByRole("button", { name: "Hesap menüsünü aç" }).click();
    await page.getByRole("menuitem", { name: /Erişilebilirlik/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    // "A+" (büyük) → <html data-text-scale="large">
    await page.locator(".acc-scale-btn").last().click();
    await expect(page.locator("html")).toHaveAttribute("data-text-scale", "large");
  });
});
