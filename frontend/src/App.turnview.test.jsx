/* TurnView render testleri — özellikle KIRMIZI ÇİZGİ (CLAUDE.md §2): reject yolundaki
   yanıt da hukuki disclaimer taşımalı. Denetim bulgusu #1 (2026-06-09 worldclass-audit). */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { TurnView } from "./App.jsx";

const html = (turn) => renderToStaticMarkup(<TurnView turn={turn} />);

describe("TurnView — reject yolu disclaimer (kırmızı çizgi §2)", () => {
  it("gerçek verify-reject backend disclaimer'ını gösterir", () => {
    const out = html({
      question: "2 yıl çalıştım, kıdem alır mıyım?",
      phase: "reject",
      data: {
        kind: "reject",
        domain: "İş Hukuku",
        reject: { title: "Bu konuda emin değilim", body: "Doğrulanmış kaynakla yanıtlayamadım." },
        disclaimers: ["Bu yanıt genel bilgilendirme amaçlıdır; bir avukata danışın."],
      },
    });
    expect(out).toContain("Bu konuda emin değilim"); // RejectCard hâlâ render olur
    expect(out).toContain('class="disclaimer"'); // DisclaimerBar eklendi
    expect(out).toContain("bir avukata danışın");
  });

  it("reject'te disclaimers yoksa (transport-hata) gereksiz hukuki disclaimer basılmaz", () => {
    const out = html({
      question: "x",
      phase: "reject",
      data: {
        kind: "reject",
        domain: "",
        reject: { title: "Bir sorun oluştu", body: "Yanıt alınamadı. Lütfen tekrar deneyin." },
        // disclaimers yok → smalltalk deseni gibi koşullu: bar basılmaz
      },
    });
    expect(out).toContain("Bir sorun oluştu");
    expect(out).not.toContain('class="disclaimer"');
  });
});
