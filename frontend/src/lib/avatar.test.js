/* avatar — deterministik tohum/baş harf/gradient testleri (saf, ağ yok). */
import { describe, it, expect } from "vitest";
import { avatarSeed, avatarInitial, avatarStyle } from "./avatar.js";

describe("avatarSeed", () => {
  it("öncelik: ad > görünen ad > e-posta > sub; küçük harfe iner", () => {
    expect(avatarSeed({ name: "Cem", email: "c@x.com", sub: "u1" }, { displayName: "X" })).toBe("cem");
    expect(avatarSeed({ email: "Ali@X.com" }, {})).toBe("ali@x.com");
    expect(avatarSeed({ sub: "u9" }, {})).toBe("u9");
    expect(avatarSeed({}, { displayName: "Veli" })).toBe("veli");
  });
  it("boş/null → 'adalet'", () => {
    expect(avatarSeed({}, {})).toBe("adalet");
    expect(avatarSeed(null, null)).toBe("adalet");
  });
});

describe("avatarInitial", () => {
  it("baş harfi büyütür", () => {
    expect(avatarInitial("cem")).toBe("C");
    expect(avatarInitial("ören")).toBe("Ö");
    expect(avatarInitial("şirket")).toBe("Ş");
  });
  it("boş → 'A'", () => {
    expect(avatarInitial("")).toBe("A");
    expect(avatarInitial("   ")).toBe("A");
  });
});

describe("avatarStyle", () => {
  it("deterministik: aynı tohum → aynı stil", () => {
    expect(avatarStyle("cem")).toEqual(avatarStyle("cem"));
  });
  it("hem gradient hem cam parlaması içerir", () => {
    const { backgroundImage } = avatarStyle("cem");
    expect(backgroundImage).toContain("linear-gradient");
    expect(backgroundImage).toContain("radial-gradient");
  });
  it("farklı tohumlar dağılır (≥4 farklı gradient)", () => {
    const seeds = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"];
    const uniq = new Set(seeds.map((s) => avatarStyle(s).backgroundImage));
    expect(uniq.size).toBeGreaterThan(3);
  });
});
