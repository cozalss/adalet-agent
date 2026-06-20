/* cards.jsx — cevap/red/netleştirme/kullanıcı-balonu render testleri (statik markup). */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { render, fireEvent } from "@testing-library/react";
import { AnswerCard, RelatedCases, RejectCard, ClarifyCard, UserBubble, SmallTalkBubble } from "./cards.jsx";

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
  it("bölümleri (label + içerik) render eder", () => {
    const answer = { sections: [{ label: "Kısa cevap", lead: true, runs: [{ t: "TÜFE sınırı" }] }] };
    const out = html(<AnswerCard answer={answer} sources={[]} />);
    expect(out).toContain("Kısa cevap");
    expect(out).toContain("TÜFE sınırı");
  });

  it("savunmacı: sections yoksa text'ten tek bölüme düşer (beyaz ekran yok)", () => {
    const out = html(<AnswerCard answer={{ text: "yalın cevap" }} sources={[]} />);
    expect(out).toContain("yalın cevap");
    expect(out).toContain("Cevap"); // fallback label
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
  it("emsal kararlarını başlık + rozet + tam-metin linkiyle render eder", () => {
    const out = html(
      <RelatedCases cases={[{ id: 2, type: "Yargıtay", badge: "yargitay",
        title: "Yargıtay 3. HD 2023/123", passage: "ihtiyaç nedeniyle tahliye...", url: "http://k" }]} />,
    );
    expect(out).toContain("related-cases");
    expect(out).toContain("İlgili Kararlar");
    expect(out).toContain("Yargıtay 3. HD 2023/123");
    expect(out).toContain("Kararın tam metni");
  });

  it("boş/eksik listede hiç render etmez (bölüm gizli)", () => {
    expect(html(<RelatedCases cases={[]} />)).toBe("");
    expect(html(<RelatedCases cases={undefined} />)).toBe("");
  });

  it("başlığa tıklayınca onJump(id) — kaynak kartına gider", () => {
    const onJump = vi.fn();
    const { getByRole } = render(
      <RelatedCases cases={[{ id: 5, title: "Yargıtay 9. HD", type: "Yargıtay" }]} onJump={onJump} />,
    );
    fireEvent.click(getByRole("button"));
    expect(onJump).toHaveBeenCalledWith(5);
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
