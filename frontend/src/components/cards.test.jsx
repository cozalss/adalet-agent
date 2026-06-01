/* cards.jsx — cevap/red/netleştirme/kullanıcı-balonu render testleri (statik markup). */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AnswerCard, RejectCard, ClarifyCard, UserBubble } from "./cards.jsx";

const html = (n) => renderToStaticMarkup(n);

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
  it("intro + numaralı seçenekler", () => {
    const out = html(<ClarifyCard data={{ intro: "Netleştirelim", options: ["Kira ne kadar", "Sözleşme var mı"] }} />);
    expect(out).toContain("Netleştirelim");
    expect(out).toContain("Kira ne kadar");
    expect(out).toContain("Sözleşme var mı");
    expect(out).toContain(">1<"); // seçenek numarası
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
