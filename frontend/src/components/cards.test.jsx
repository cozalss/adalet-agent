/* cards.jsx — cevap/red/netleştirme/kullanıcı-balonu render testleri (statik markup). */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { render, fireEvent } from "@testing-library/react";
import { fetchFullDecision } from "../lib/api.js";
import { AnswerCard, RelatedCases, RejectCard, ClarifyCard, UserBubble, SmallTalkBubble } from "./cards.jsx";

// İlgili Kararlar "tam metni getir" canlı çekmeyi mock'la (ağ yok).
vi.mock("../lib/api.js", () => ({ fetchFullDecision: vi.fn() }));

const html = (n) => renderToStaticMarkup(n);

describe("SmallTalkBubble", () => {
  it("hafif baloncuk: metin render, KART değil (gölge/border yok)", () => {
    const out = html(<SmallTalkBubble text={"Merhaba! Ben ADALET.\n\nYardımcı olabilirim."} />);
    expect(out).toContain("Merhaba! Ben ADALET.");
    expect(out).toContain("Yardımcı olabilirim.");
    expect(out).toContain("smalltalk-bubble");
    expect(out).not.toContain('class="card'); // kart değil → soğuk RejectCard hissi yok
  });
});

describe("AnswerCard", () => {
  it("lead etiketini GİZLER (robotik 'Kısa cevap:' başlığı yok), ikincil etiketi GÖSTERİR", () => {
    const answer = { sections: [
      { label: "Kısa cevap", lead: true, runs: [{ t: "TÜFE sınırı" }] },
      { label: "Dayanak", runs: [{ t: "TBK 344" }] },
    ] };
    const out = html(<AnswerCard answer={answer} sources={[]} />);
    expect(out).toContain("TÜFE sınırı");      // lead içeriği görünür
    expect(out).not.toContain("Kısa cevap");   // lead etiketi GİZLİ (doğal açılış metni)
    expect(out).toContain("Dayanak");          // ikincil etiket GÖRÜNÜR (taranabilirlik)
    expect(out).toContain("TBK 344");
  });

  it("savunmacı: sections yoksa text'ten tek lead bölüme düşer (etiketsiz saf metin)", () => {
    const out = html(<AnswerCard answer={{ text: "yalın cevap" }} sources={[]} />);
    expect(out).toContain("yalın cevap");
    expect(out).not.toContain("sec-label"); // tek lead → etiket yok (saf prose)
  });

  it("steps bölümünü <ol><li> olarak render eder", () => {
    const answer = { sections: [{ label: "Ne yapmalı", steps: ["adım bir", "adım iki"] }] };
    const out = html(<AnswerCard answer={answer} sources={[]} />);
    expect(out).toContain("<ol");
    expect(out).toContain("adım bir");
    expect(out).toContain("adım iki");
  });
});

describe("RejectCard", () => {
  it("başlık + body + avukat bul linki", () => {
    const out = html(<RejectCard data={{ title: "Emin değilim", body: "kaynak bulunamadı" }} />);
    expect(out).toContain("Emin değilim");
    expect(out).toContain("kaynak bulunamadı");
    expect(out).toContain("barobirlik.org.tr");
  });
});

describe("ClarifyCard", () => {
  it("yumuşak: intro + ok-ipuçlu seçenekler (numara değil)", () => {
    const out = html(<ClarifyCard data={{ intro: "Netleştirelim", options: ["Kira ne kadar", "Sözleşme var mı"] }} />);
    expect(out).toContain("Netleştirelim");
    expect(out).toContain("Kira ne kadar");
    expect(out).toContain("Sözleşme var mı");
    expect(out).toContain("clarify soft"); // glass-ağırlık yerine yumuşak ton
    expect(out).toContain("cl-arrow"); // numara değil ok-ipucu
    expect(out).not.toContain('class="num"'); // eski diktat numarası KALDIRILDI
  });

  it("chips verilince tıklanabilir cevap-şıkları (button.cl-chip) render eder", () => {
    const out = html(
      <ClarifyCard data={{ intro: "Sebep?", options: ["Neden çıkarmak istiyorsunuz?"],
        chips: ["İhtiyaç nedeniyle", "Kira ödenmiyor (temerrüt)"] }} />,
    );
    expect(out).toContain("cl-chip");
    expect(out).toContain("İhtiyaç nedeniyle");
    expect(out).toContain("Kira ödenmiyor (temerrüt)");
    expect(out).toContain("<button");
  });

  it("chip'e tıklayınca onPick(chip) çağrılır — sebep CEVAP olarak gider", () => {
    const onPick = vi.fn();
    const { getByText } = render(
      <ClarifyCard data={{ intro: "Sebep?", options: ["x"], chips: ["İhtiyaç nedeniyle"] }}
        onPick={onPick} />,
    );
    fireEvent.click(getByText("İhtiyaç nedeniyle"));
    expect(onPick).toHaveBeenCalledWith("İhtiyaç nedeniyle");
  });

  it("chips yoksa eski davranış: cevap-şıkkı (cl-chip) basılmaz", () => {
    const out = html(<ClarifyCard data={{ intro: "i", options: ["a", "b"] }} />);
    expect(out).not.toContain("cl-chip");
  });

  it("savunmacı: options tanımsızsa render çökmez (geçmiş-replay/bozuk yanıt)", () => {
    expect(() => html(<ClarifyCard data={{ intro: "x" }} />)).not.toThrow();
  });
});

describe("RelatedCases", () => {
  it("emsal kararını başlık + rozet + özet + 'tam metnini getir' butonuyla render eder (link YOK)", () => {
    const out = html(
      <RelatedCases cases={[{ id: 2, type: "Yargıtay", badge: "yargitay", title: "Yargıtay 3. HD 2023/123",
        passage: "ihtiyaç nedeniyle tahliye yargılaması",
        url: "https://karararama.yargitay.gov.tr/?aranan=1", ref: "h-1-c0" }]} />,
    );
    expect(out).toContain("related-cases");
    expect(out).toContain("İlgili Kararlar");
    expect(out).toContain("Yargıtay 3. HD 2023/123");
    expect(out).toContain("ihtiyaç nedeniyle tahliye yargılaması");  // özet tam (kesik değil)
    expect(out).toContain("Kararın tam metnini getir");             // on-demand buton
    expect(out).not.toContain("rc-link");                            // arama linki yok
  });

  it("url/ref yoksa 'tam metnini getir' butonu çıkmaz", () => {
    const out = html(<RelatedCases cases={[{ id: 3, type: "Yargıtay", title: "Y", passage: "özet" }]} />);
    expect(out).not.toContain("tam metnini getir");
  });

  it("boş/eksik listede hiç render etmez (bölüm gizli)", () => {
    expect(html(<RelatedCases cases={[]} />)).toBe("");
    expect(html(<RelatedCases cases={undefined} />)).toBe("");
  });

  it("panel açılınca tam metni OTOMATİK getirir ve baştan gösterir (tıklama yok)", async () => {
    fetchFullDecision.mockResolvedValue({ text: "8. HD İçtihat Metni: tam karar gövdesi burada", cached: false, error: null });
    const { findByText } = render(
      <RelatedCases cases={[{ id: 9, type: "Yargıtay", title: "Y 8.HD", passage: "özet parça",
        url: "https://karararama.yargitay.gov.tr/?aranan=525485900", ref: "h-525485900-c1" }]} />,
    );
    // mount'ta otomatik yüklenir → tam metnin BAŞI görünür
    expect(await findByText(/tam karar gövdesi/)).toBeTruthy();
    expect(fetchFullDecision.mock.calls[0][0]).toEqual({
      source_url: "https://karararama.yargitay.gov.tr/?aranan=525485900", source_id: "h-525485900-c1", court: "Yargıtay",
    });
  });

  it("uzun kararı BAŞTAN önizler (~420 krk) + 'tam metnini göster' ile açar", async () => {
    const long = "BAŞLANGIÇ " + "x".repeat(600) + " SONUC";
    fetchFullDecision.mockResolvedValue({ text: long, cached: false, error: null });
    const { findByText, getByText, queryByText } = render(
      <RelatedCases cases={[{ id: 11, type: "Yargıtay", title: "Y", url: "https://x", ref: "r" }]} />,
    );
    await findByText(/BAŞLANGIÇ/);          // baştan gösterildi
    expect(queryByText(/SONUC/)).toBeNull();  // 420'den sonrası önizlemede gizli
    fireEvent.click(getByText("Kararın tam metnini göster"));
    expect(getByText(/SONUC/)).toBeTruthy();  // expand → tam metin
  });

  it("getirme başarısızsa kullanıcı-dostu hata gösterir (uydurmaz, mount'ta otomatik)", async () => {
    fetchFullDecision.mockResolvedValue({ text: "", cached: false, error: "rate_limited" });
    const { findByText } = render(
      <RelatedCases cases={[{ id: 10, type: "Yargıtay", title: "Y", url: "https://karararama.yargitay.gov.tr/?aranan=1", ref: "h-1-c0" }]} />,
    );
    expect(await findByText(/yoğunluk/i)).toBeTruthy();
  });
});

describe("UserBubble", () => {
  it("metni balonda gösterir", () => {
    expect(html(<UserBubble text="benim sorum" />)).toContain("benim sorum");
  });
  it("onEdit verilince düzenle butonu render eder", () => {
    const out = html(<UserBubble text="x" onEdit={() => {}} />);
    expect(out).toContain("Mesajı düzenle");
  });
});
