/* usePrefs.sanitize — tercih doğrulama/savunmacı kırpma testleri. */
import { describe, it, expect } from "vitest";
import { sanitize, DEFAULT_PREFS } from "./usePrefs.js";

describe("sanitize", () => {
  it("boş/çöp girdide varsayılana düşer", () => {
    expect(sanitize(null)).toEqual(DEFAULT_PREFS);
    expect(sanitize("x")).toEqual(DEFAULT_PREFS);
    expect(sanitize(undefined)).toEqual(DEFAULT_PREFS);
  });

  it("bilinmeyen yazı boyutunu 'normal'e çeker", () => {
    expect(sanitize({ textScale: "huge" }).textScale).toBe("normal");
    expect(sanitize({ textScale: "large" }).textScale).toBe("large");
    expect(sanitize({ textScale: "compact" }).textScale).toBe("compact");
  });

  it("yalnız 8 sivil alanı tutar, tekrarı atar, 8 ile sınırlar", () => {
    const out = sanitize({
      preferredDomains: ["kira", "ceza", "kira", "tuketici", "aile", "uydurma", "isHukuku"],
    });
    expect(out.preferredDomains).toEqual(["kira", "tuketici", "isHukuku"]);
  });

  it("preferredDomains dizi değilse boş döner", () => {
    expect(sanitize({ preferredDomains: "kira" }).preferredDomains).toEqual([]);
  });

  it("displayName'i 60 karaktere kırpar, string değilse boşaltır", () => {
    expect(sanitize({ displayName: "a".repeat(80) }).displayName).toHaveLength(60);
    expect(sanitize({ displayName: 123 }).displayName).toBe("");
  });

  it("reduceMotion/highContrast'ı boolean'a zorlar", () => {
    const out = sanitize({ reduceMotion: 1, highContrast: 0 });
    expect(out.reduceMotion).toBe(true);
    expect(out.highContrast).toBe(false);
  });

  it("şema versiyonunu her zaman ekler", () => {
    expect(sanitize({}).v).toBe(1);
  });
});
