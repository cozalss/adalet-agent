/* LegalTooltip — hukuki terim tooltip'i a11y (#37): touch/klavye erişimi + SR. */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { applyLegalTooltips } from "./LegalTooltip.jsx";

describe("applyLegalTooltips (a11y #37)", () => {
  it("hukuki terimi klavye/dokunmatik-erişilebilir abbr ile sarar (tabindex + role + aria-label)", () => {
    const nodes = applyLegalTooltips("Bu durumda kıdem tazminatı hakkınız doğar.", "k");
    const out = renderToStaticMarkup(<>{nodes}</>);
    expect(out).toContain("kıdem tazminatı");
    expect(out).toContain('tabindex="0"');   // odaklanabilir → :focus tooltip (touch/klavye)
    expect(out).toContain('role="note"');
    expect(out).toContain("aria-label=");     // tanım ekran-okuyucuya da duyurulur
  });

  it("hukuki terim yoksa düz metni değiştirmeden döndürür", () => {
    expect(applyLegalTooltips("merhaba dünya nasılsın", "k")).toBe("merhaba dünya nasılsın");
  });

  it("string olmayan/boş girdiyi olduğu gibi döndürür", () => {
    expect(applyLegalTooltips("", "k")).toBe("");
    expect(applyLegalTooltips(null, "k")).toBe(null);
  });
});
