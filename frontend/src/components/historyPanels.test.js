/* relDate — ISO tarih → kısa Türkçe (mutasyonsuz) testleri. */
import { describe, it, expect } from "vitest";
import { relDate } from "./historyPanels.jsx";

/** N gün önce (yerel) → ISO. relDate round-trip'i tz-bağımsız çözmeli. */
function daysAgoIso(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString();
}

describe("relDate", () => {
  it("boş/geçersiz girdi → ''", () => {
    expect(relDate("")).toBe("");
    expect(relDate(null)).toBe("");
    expect(relDate("çöp-tarih")).toBe("");
  });

  it("bugün → 'bugün'", () => {
    expect(relDate(new Date().toISOString())).toBe("bugün");
  });

  it("dün → 'dün'", () => {
    expect(relDate(daysAgoIso(1))).toBe("dün");
  });

  it("3 gün → '3 gün önce'", () => {
    expect(relDate(daysAgoIso(3))).toBe("3 gün önce");
  });

  it("7+ gün → tarih biçimi (gün/ay), 'gün önce' değil", () => {
    const out = relDate(daysAgoIso(10));
    expect(out).not.toContain("gün önce");
    expect(out).toMatch(/\d/); // gün numarası içerir
  });
});
