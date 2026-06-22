/* Küçük bileşen render testleri — StreamStepper / Badge / SourceCard /
   ConversationList / Modal (renderToStaticMarkup; components kapsamını yükseltir). */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { StreamStepper, Badge, SourceCard } from "./ui.jsx";
import { ConversationList } from "./ConversationList.jsx";
import { Modal } from "./Modal.jsx";

const html = (n) => renderToStaticMarkup(n);

describe("StreamStepper", () => {
  it("faz → adım eşler (progressbar aria-valuenow)", () => {
    const out = html(<StreamStepper phase="sources" />);
    expect(out).toContain('aria-valuenow="2"'); // sources = idx 1 → 2
    expect(out).toContain("Kaynaklar aranıyor");
    expect(out).toContain('role="progressbar"');
  });
  it("verifying → 4. adım (doğrulama)", () => {
    expect(html(<StreamStepper phase="verifying" />)).toContain('aria-valuenow="4"');
  });
  it("customLabel yalnız triage (ilk adım) için kullanılır", () => {
    expect(html(<StreamStepper phase="triage" customLabel="Özel etiket" />)).toContain("Özel etiket");
  });
  it("triage fazında 1. adım + sınıflandırma etiketi (artık baştan stepper)", () => {
    const out = html(<StreamStepper phase="triage" />);
    expect(out).toContain('aria-valuenow="1"');
    expect(out).toContain("sınıflandırılıyor");
  });
  it("a11y: aşama değişimini duyuran aria-live bölgesi var", () => {
    const out = html(<StreamStepper phase="sources" />);
    expect(out).toContain('aria-live="polite"');
    expect(out).toContain("Aşama:");
  });
});

describe("Badge", () => {
  it("kanun → book ikonu + tip metni", () => {
    const out = html(<Badge type="Kanun" badge="kanun" />);
    expect(out).toContain("Kanun");
    expect(out).toContain("badge kanun");
  });
});

describe("SourceCard", () => {
  const s = {
    id: 1, type: "Kanun", badge: "kanun", title: "TBK m.344", ref: "tbk-344",
    passage: "madde metni", url: "mevzuat.gov.tr", verified: true, rel: [1],
  };
  it("kanun mührü + başlık + doğrulandı + data-src-id; dış mevzuat linki gösterilmez", () => {
    const out = html(<SourceCard s={s} />);
    expect(out).toContain("TBK m.344");
    expect(out).toContain("Doğrulandı");
    expect(out).toContain("madde metni");
    expect(out).not.toContain("mevzuat.gov.tr");
    expect(out).toContain('data-src-id="1"');
  });
  it("yargıtay (case) → yargitay badge", () => {
    expect(html(<SourceCard s={{ ...s, badge: "yargitay", type: "Yargıtay" }} />)).toContain("badge yargitay");
  });
  it("karar kaynaklarında dış link gösterilir", () => {
    const out = html(<SourceCard s={{
      ...s,
      badge: "yargitay",
      type: "Yargıtay",
      url: "https://karararama.yargitay.gov.tr/?aranan=123",
    }} />);

    expect(out).toContain("karararama.yargitay.gov.tr");
  });
  it("kanun maddesi: fullText önizlemeden uzunsa 'Tam maddeyi göster' + baştan önizleme (tam GİZLİ)", () => {
    const out = html(<SourceCard s={{
      ...s, passage: "MADDE 8 onizleme", fullText: "MADDE 8 onizleme " + "x".repeat(500) + " TAMSON",
    }} />);
    expect(out).toContain("Tam maddeyi göster");  // expand butonu
    expect(out).toContain("MADDE 8 onizleme");     // baştan önizleme gösterilir
    expect(out).not.toContain("TAMSON");           // tam metin default gizli (expand'da açılır)
  });
  it("kısa madde (fullText ≈ passage) → expand butonu YOK", () => {
    expect(html(<SourceCard s={{ ...s, passage: "kısa madde", fullText: "kısa madde" }} />))
      .not.toContain("Tam maddeyi göster");
  });
});

describe("ConversationList", () => {
  it("boş → geçmiş notu", () => {
    expect(html(<ConversationList conversations={[]} />)).toContain("Sohbet geçmişiniz burada");
  });
  it("liste → başlık + sil butonu + aktif vurgu", () => {
    const out = html(<ConversationList
      conversations={[{ id: "c1", title: "Kira sorunu", updatedAt: new Date().toISOString() }]}
      activeId="c1" />);
    expect(out).toContain("Kira sorunu");
    expect(out).toContain("Sohbeti sil");
    expect(out).toContain("active");
  });
});

describe("Modal", () => {
  it("başlık + içerik + kapat + role=dialog", () => {
    const out = html(<Modal title="Başlık" onClose={() => {}}><p>panel içeriği</p></Modal>);
    expect(out).toContain("Başlık");
    expect(out).toContain("panel içeriği");
    expect(out).toContain("Kapat");
    expect(out).toContain('role="dialog"');
    expect(out).toContain('aria-modal="true"');
  });
});
