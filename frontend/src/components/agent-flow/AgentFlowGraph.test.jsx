/* AgentFlowGraph render smoke (renderToStaticMarkup). Görsel-mantık topology.test.js'te;
   burada DOM/a11y çıktısı + props→render doğrulanır. */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AgentFlowGraph } from "./AgentFlowGraph.jsx";

const html = (n) => renderToStaticMarkup(n);

describe("AgentFlowGraph", () => {
  it("role=figure + aria-label + 7 düğüm etiketi", () => {
    const out = html(<AgentFlowGraph phase="triage" />);
    expect(out).toContain('role="figure"');
    expect(out).toContain('aria-label="Ajan akış şeması"');
    for (const label of ["Triaj", "Mevzuat", "Emsal", "Taslak", "Doğrulama", "Tartışma", "Sonuç"]) {
      expect(out).toContain(label);
    }
  });

  it("retrieval aktif → mevzuat+emsal active sınıfı + paralel figcaption", () => {
    const out = html(<AgentFlowGraph activeNode="retrieval" sources={{ mevzuat: 3, emsal: 2 }} />);
    expect(out).toContain("agw-node-active");
    expect(out).toContain("agw-node-done"); // triaj done
    expect(out).toMatch(/Mevzuat ve Emsal/);
    expect(out).toContain("3 kanun"); // kaynak chip
    expect(out).toContain("2 içtihat");
  });

  it("final → tüm düğümler done + doğrulama rozeti (metin-kodlu, backend kararı)", () => {
    const out = html(
      <AgentFlowGraph phase="final" verify={{ nVerified: 4, nTotal: 5, confidenceLabel: "Yüksek güven" }} />,
    );
    expect(out).toContain("agw-node-done");
    expect(out).not.toContain("agw-node-active");
    expect(out).toContain("4/5");
    expect(out).toContain("iddia doğrulandı");
    expect(out).toContain("Güven: Yüksek güven");
    expect(out).toContain("agw-verify-high"); // ton sınıfı GERÇEK etikete uygulanıyor (renk-kodu)
    // a11y: rozet aria-label tam cümle
    expect(out).toMatch(/Doğrulama: 4\/5 iddia kaynakla doğrulandı/);
  });

  it("final düşük güven → agw-verify-low (danger tonu)", () => {
    const out = html(
      <AgentFlowGraph phase="final" verify={{ nVerified: 1, nTotal: 4, confidenceLabel: "Dikkatli olun" }} />,
    );
    expect(out).toContain("agw-verify-low");
    expect(out).toContain("1/4");
    expect(out).toContain("Güven: Dikkatli olun");
  });

  it("retry → 'yeniden üretiliyor' rozeti + retry kenarı", () => {
    const out = html(<AgentFlowGraph activeNode="draft" retryCount={2} />);
    expect(out).toContain("yeniden üretiliyor (2)");
    expect(out).toContain("agw-edge-retry");
  });

  it("smalltalk intent → skipped düğümler (HATA değil), figure yine render", () => {
    const out = html(<AgentFlowGraph activeNode={null} phase="triage" intent="smalltalk" />);
    expect(out).toContain("agw-node-skipped");
    expect(out).toContain('role="figure"');
  });

  it("a11y: figcaption + aria-live status canlı cümle taşır", () => {
    const out = html(<AgentFlowGraph activeNode="draft" />);
    expect(out).toContain("<figcaption");
    expect(out).toContain('role="status"');
    expect(out).toContain('aria-live="polite"');
  });
});
