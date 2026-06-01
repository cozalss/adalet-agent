import { test, expect } from "@playwright/test";

/* Sohbet geçmişi — localStorage'a enjekte edilmiş kayıtlar (backend'siz). */
const CONV = {
  c1: {
    id: "c1", title: "Kira zammı sorunu", domain: "Kira Hukuku",
    createdAt: "2026-05-30T10:00:00Z", updatedAt: "2026-05-31T10:00:00Z",
    turns: [{
      question: "Ev sahibim fahiş zam istiyor", phase: "final",
      data: {
        kind: "answer", domain: "Kira Hukuku",
        answer: { confidence: 88, text: "TÜFE sınırı", sections: [{ label: "Cevap", lead: true, runs: [{ t: "Yasal sınır TÜFE ortalamasıdır." }] }] },
        sources: [{ id: 1, title: "TBK m.344", doc_type: "law" }], disclaimers: ["Hukuki tavsiye değildir."],
      },
    }],
    files: [{ filename: "kira.pdf", n_chars: 1200, pii: true }],
  },
};

test.describe("Sohbet geçmişi", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((c) => {
      localStorage.setItem("adalet.conversations", JSON.stringify(c));
    }, CONV);
    await page.goto("/?e2e=1"); // auth'u atla (VITE_E2E build) → App + enjekte localStorage geçmişi
  });

  test("geçmiş sidebar'da listelenir + tıkla → yükle", async ({ page }) => {
    await expect(page.getByText("Sohbet geçmişi")).toBeVisible();
    const item = page.getByRole("button", { name: /Kira zammı sorunu/ });
    await expect(item).toBeVisible();
    await item.click();
    await expect(page.getByText("Yasal sınır TÜFE ortalamasıdır.")).toBeVisible();
  });

  test("Kaynaklar paneli sohbetteki atfı gösterir", async ({ page }) => {
    await page.getByRole("button", { name: "Kaynaklar" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("TBK m.344")).toBeVisible();
  });

  test("Dosyalarım paneli yüklenen belgeyi gösterir", async ({ page }) => {
    await page.getByRole("button", { name: "Dosyalarım" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("kira.pdf")).toBeVisible();
  });
});
