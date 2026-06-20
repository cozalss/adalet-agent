/* panels.jsx — PredictionCard / AgentTrace özet / EvidenceStats render testleri. */
import React from "react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { PredictionCard, AgentTrace, AnswerFooter, EvidenceStats, QuickTyping } from "./panels.jsx";

// NumberTicker (framer-motion useInView) jsdom'da IntersectionObserver arar — full render
// (fireEvent) testlerinde stub. Statik markup testleri bunu kullanmaz.
beforeAll(() => {
  global.IntersectionObserver = class {
    observe() {} unobserve() {} disconnect() {} takeRecords() { return []; }
  };
});

const html = (n) => renderToStaticMarkup(n);

describe("AgentTrace a11y (#37)", () => {
  it("toggle aria-controls açılan bölgenin id'siyle eşleşir (aria-expanded tek başına yetmez)", () => {
    render(<AgentTrace claims={[{ verified: true }]} sourceCount={2} domain="kira" />);
    const btn = screen.getByRole("button", { name: /doğrulama dökümü/i });
    const controls = btn.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(btn);  // bölgeyi aç
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    const body = document.getElementById(controls);
    expect(body).not.toBeNull();
    expect(body.className).toContain("at-body");
  });
});

describe("QuickTyping", () => {
  it("role=status + 3 nokta + etiket", () => {
    const out = html(<QuickTyping label="Yazıyor" />);
    expect(out).toContain('role="status"');
    expect(out).toContain("Yazıyor");
    expect((out.match(/qt-dot"/g) || []).length).toBe(3); // 3 nokta (kapsayıcı qt-dots hariç)
  });
});

describe("PredictionCard", () => {
  it("null tahmin → hiçbir şey render etmez", () => {
    expect(html(<PredictionCard prediction={null} />)).toBe("");
  });

  it("kazandi → lehe eğilim + % + tone-ok + gerekçe + zorunlu disclaimer", () => {
    const out = html(<PredictionCard prediction={{
      verdictClass: "kazandi", confidence: 70, similarCaseIds: ["E.2021/1", "E.2020/2"],
      reasoning: "benzer kararlar lehe", disclaimer: "mahkeme garantisi değildir",
    }} />);
    expect(out).toContain("Lehe eğilim");
    expect(out).toContain("%70");
    expect(out).toContain("tone-ok");
    expect(out).toContain("benzer kararlar lehe");
    expect(out).toContain("mahkeme garantisi değildir");
    expect(out).toContain("E.2021/1");
  });

  it("8 emsale kadar tüm çipleri gösterir (reasoning sayısıyla tutarlı)", () => {
    const ids = Array.from({ length: 8 }, (_, i) => `9. HD 2020/${1000 + i}`);
    const out = html(<PredictionCard prediction={{
      verdictClass: "kazandi", confidence: 75, similarCaseIds: ids,
      reasoning: "8 emsalden 6'sı lehine", disclaimer: "d",
    }} />);
    ids.forEach((id) => expect(out).toContain(id));   // 8'inin hepsi görünür (6'da kesilmez)
    expect(out).not.toContain("pred-case more");        // 8'de taşma yok
  });

  it("8'den fazla emsalde +N taşma göstergesi (dürüst, gizli mismatch yok)", () => {
    const ids = Array.from({ length: 11 }, (_, i) => `K-${i}`);
    const out = html(<PredictionCard prediction={{
      verdictClass: "kazandi", confidence: 70, similarCaseIds: ids,
      reasoning: "r", disclaimer: "d",
    }} />);
    expect(out).toContain("+3");                        // 11 - 8 = 3 daha
  });

  it("belirsiz → yüzde/bar gösterilmez", () => {
    const out = html(<PredictionCard prediction={{ verdictClass: "belirsiz", confidence: 0, similarCaseIds: [], disclaimer: "d" }} />);
    expect(out).toContain("Belirsiz");
    expect(out).not.toContain("pred-bar");
    expect(out).not.toContain("pred-pct");
  });
});

describe("AgentTrace (özet)", () => {
  it("iddia + debate yoksa → hiçbir şey render etmez", () => {
    expect(html(<AgentTrace claims={[]} sourceCount={0} />)).toBe("");
  });

  it("iddia özetini hesaplar (X/Y doğrulandı)", () => {
    const out = html(<AgentTrace claims={[{ verified: true }, { verified: false }]} sourceCount={3} domain="kira" />);
    expect(out).toContain("1/2 iddia kaynakla doğrulandı");
  });

  it("tahmin VARSAYILAN GİZLİ (collapsed) — açılınca PredictionCard görünür (progressive-disclosure)", () => {
    const pred = { verdictClass: "kaybetti", confidence: 42, similarCaseIds: ["K-1"], reasoning: "r", disclaimer: "d" };
    // Kapalıyken: tahmin metni DOM'da yok (at-body render edilmez)
    const closed = html(<AgentTrace claims={[{ verified: true }]} sourceCount={2} domain="tuketici" prediction={pred} />);
    expect(closed).not.toContain("Aleyhe eğilim");
    // Açınca: PredictionCard at-body içinde
    render(<AgentTrace claims={[{ verified: true }]} sourceCount={2} domain="tuketici" prediction={pred} />);
    fireEvent.click(screen.getByRole("button", { name: /doğrulama dökümü/i }));
    expect(screen.getByText(/Aleyhe eğilim/)).toBeTruthy();
  });

  it("yalnız tahmin (iddia/debate yok) varsa yine render eder", () => {
    const pred = { verdictClass: "belirsiz", confidence: 0, similarCaseIds: [], disclaimer: "d" };
    expect(html(<AgentTrace claims={[]} sourceCount={0} prediction={pred} />)).not.toBe("");
  });
});

describe("AnswerFooter (sade kaynak/karar bağlantıları)", () => {
  it("kaynak ve karar yoksa → hiçbir şey render etmez", () => {
    expect(html(<AnswerFooter sourceCount={0} caseCount={0} />)).toBe("");
  });

  it("Kaynaklar + İlgili Kararlar sayılarını gösterir; güven% YOK", () => {
    const out = html(<AnswerFooter sourceCount={2} caseCount={4} onOpenSources={() => {}} onOpenCases={() => {}} />);
    expect(out).toContain("Kaynaklar");
    expect(out).toContain("İlgili Kararlar");
    expect(out).toContain(">2<");
    expect(out).toContain(">4<");
    expect(out).not.toContain("Güven");   // kalibre-olmayan güven% kaldırıldı
  });

  it("Kaynaklar bağlantısına tıklayınca onOpenSources çağrılır (yan panel)", () => {
    const onOpenSources = vi.fn();
    render(<AnswerFooter sourceCount={3} onOpenSources={onOpenSources} caseCount={0} />);
    fireEvent.click(screen.getByLabelText(/kaynak — yan panelde göster/i));
    expect(onOpenSources).toHaveBeenCalled();
  });

  it("callback yoksa düz metin (buton/pill DEĞİL — yanıltıcı etkileşim yok)", () => {
    const out = html(<AnswerFooter sourceCount={2} caseCount={0} />);
    expect(out).toContain("af-static");
    expect(out).not.toContain("af-link");   // pill/buton stili verilmez
    expect(out).not.toContain("<button");
  });
});

describe("EvidenceStats", () => {
  it("kaynak sayısı + doğrulanan iddia (X/Y) gösterir", () => {
    const out = html(<EvidenceStats confidence={88} sourceCount={5}
      claims={[{ verified: true }, { verified: true }, { verified: false }]} />);
    expect(out).toContain("Güven");
    expect(out).toContain("Kaynak");
    expect(out).toContain(">5<");           // sourceCount
    expect(out).toContain("Doğrulanan iddia");
    expect(out).toContain(">2<");           // verified
    expect(out).toContain("/3");            // total
  });

  it("iddia yoksa doğrulanan-iddia bloğu gösterilmez", () => {
    const out = html(<EvidenceStats confidence={50} sourceCount={2} claims={[]} />);
    expect(out).not.toContain("Doğrulanan iddia");
  });

  it("güven göstergesi 'kalibre olasılık değil' diye dürüstçe etiketlenir (#3)", () => {
    const out = html(<EvidenceStats confidence={88} sourceCount={5} claims={[]} />);
    // tooltip + aria: kullanıcı %88'i kalibre doğruluk olasılığı sanmasın
    expect(out).toContain("kalibre edilmiş doğruluk olasılığı DEĞİLDİR");
    expect(out).toContain("sezgisel, kalibre olasılık değil");
  });

  it("dava varsa 'İlgili Kararlar' tıklanabilir stat'ı gösterir (Doğrulanan iddia yerine)", () => {
    const out = html(<EvidenceStats confidence={88} sourceCount={5}
      claims={[{ verified: true }, { verified: false }]} caseCount={3} onOpenCases={() => {}} />);
    expect(out).toContain("İlgili Kararlar");
    expect(out).toContain(">3<");                 // caseCount
    expect(out).not.toContain("Doğrulanan iddia"); // yerine geçti
  });

  it("İlgili Kararlar stat'ına tıklayınca onOpenCases çağrılır (yan panel açılır)", () => {
    const onOpenCases = vi.fn();
    render(<EvidenceStats confidence={88} sourceCount={5} claims={[]} caseCount={2} onOpenCases={onOpenCases} />);
    fireEvent.click(screen.getByLabelText(/ilgili karar/i));
    expect(onOpenCases).toHaveBeenCalled();
  });

  it("dava yoksa eski 'Doğrulanan iddia' stat'ı korunur (bilgi kaybı yok)", () => {
    const out = html(<EvidenceStats confidence={88} sourceCount={5}
      claims={[{ verified: true }]} caseCount={0} onOpenCases={() => {}} />);
    expect(out).toContain("Doğrulanan iddia");
    expect(out).not.toContain("İlgili Kararlar");
  });
});
