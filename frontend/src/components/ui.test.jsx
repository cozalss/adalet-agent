/* ui.jsx render helper'ları + legalTerms — markdown/legal-tooltip/disclaimer testleri.
   React node'ları renderToStaticMarkup ile HTML'e basıp doğrularız (yeni dep yok). */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { RiskWarning, DisclaimerBar, RunText } from "./ui.jsx";
import { applyLegalTooltips } from "./LegalTooltip.jsx";
import { findLegalTerms } from "../lib/legalTerms.js";

const html = (node) => renderToStaticMarkup(node);

describe("findLegalTerms", () => {
  it("terimi konum + tanımla bulur", () => {
    const hits = findLegalTerms("Kıdem tazminatı nasıl hesaplanır?");
    expect(hits).toHaveLength(1);
    expect(hits[0].term).toBe("kıdem tazminatı");
    expect(hits[0].idx).toBe(0);
    expect(hits[0].def).toContain("30 günlük");
  });
  it("birden çok terimi konum sırasıyla döner", () => {
    const hits = findLegalTerms("zamanaşımı ve tebliğ çok önemli");
    expect(hits.map((h) => h.term)).toEqual(["zamanaşımı", "tebliğ"]);
  });
  it("terim yoksa / boş → null", () => {
    expect(findLegalTerms("merhaba dünya")).toBeNull();
    expect(findLegalTerms("")).toBeNull();
  });
});

describe("applyLegalTooltips", () => {
  it("hukuki terimi <abbr class='legal-term'> ile sarar (tanım data-def)", () => {
    const out = html(<>{applyLegalTooltips("kıdem tazminatı hesabı", "k")}</>);
    expect(out).toContain('class="legal-term"');
    expect(out).toContain("data-def=");
    expect(out).toContain("kıdem tazminatı");
  });
  it("terim yoksa metni değiştirmez", () => {
    expect(applyLegalTooltips("sıradan metin", "k")).toBe("sıradan metin");
  });
  it("string olmayan girdiyi aynen döner", () => {
    expect(applyLegalTooltips(null, "k")).toBeNull();
  });
});

describe("renderInline (RiskWarning üzerinden)", () => {
  it("**kalın** → <strong>", () => {
    expect(html(<RiskWarning text="bu **süre** önemli" />)).toContain("<strong>süre</strong>");
  });
  it("*italik* → <em>", () => {
    expect(html(<RiskWarning text="bu *vurgu* var" />)).toContain("<em>vurgu</em>");
  });
  it("yıldız yoksa düz metin (strong/em yok)", () => {
    const out = html(<RiskWarning text="düz uyarı metni" />);
    expect(out).toContain("düz uyarı metni");
    expect(out).not.toContain("<strong>");
    expect(out).not.toContain("<em>");
  });
});

describe("RunText", () => {
  it("cite run → kaynak işaretçisi (numara + .cite)", () => {
    const out = html(
      <RunText runs={[{ cite: 1 }]} sources={[{ id: 1, title: "TBK", type: "Kanun", badge: "kanun", ref: "r" }]} />
    );
    expect(out).toContain('class="cite"');
    expect(out).toContain(">1<");
  });
  it("metin run → hukuki terim tooltip uygular", () => {
    const out = html(<RunText runs={[{ t: "kıdem tazminatı tutarı" }]} sources={[]} />);
    expect(out).toContain('class="legal-term"');
  });
});

describe("DisclaimerBar", () => {
  it("backend disclaimer'ları birleştirir", () => {
    const out = html(<DisclaimerBar items={["Uyarı bir.", "Uyarı iki."]} />);
    expect(out).toContain("Uyarı bir. Uyarı iki.");
  });
  it("boş/eksik → statik fallback (avukat)", () => {
    expect(html(<DisclaimerBar items={[]} />)).toContain("avukat");
    expect(html(<DisclaimerBar items={undefined} />)).toContain("avukat");
  });
});
