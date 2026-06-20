/* TurnView render testleri — özellikle KIRMIZI ÇİZGİ (CLAUDE.md §2): reject yolundaki
   yanıt da hukuki disclaimer taşımalı. Denetim bulgusu #1 (2026-06-09 worldclass-audit).
   + MsgActions sesli "Dinle" (#7). */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { TurnView, MsgActions, AttachRow } from "./App.jsx";
import * as api from "./lib/api.js";

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

describe("TurnView — hukuki yol CANLI akış (boş ekran fix)", () => {
  it("token öncesi (sources fazı) StreamStepper gösterir — ekran boş kalmaz", () => {
    const out = html({
      question: "İnternetten aldığım ürün ayıplı çıktı, iade hakkım var mı?",
      phase: "sources",
      data: { kind: "answer", domain: "Tüketici Hukuku", sourceCount: 0, draftText: "" },
    });
    expect(out).toContain("progressbar");                 // StreamStepper render edildi
    expect(out).toContain("Kaynaklar aranıyor");           // sources adım etiketi
  });

  it("drafting fazında biriken draftText'i canlı baloncukta yazar (ChatGPT hissi)", () => {
    const out = html({
      question: "Kira sözleşmem feshedildi, ne yapabilirim?",
      phase: "drafting",
      data: { kind: "answer", domain: "Kira Hukuku", draftText: "Kira sözleşmesinin feshi halinde" },
    });
    expect(out).toContain("draft-stream");                 // canlı taslak baloncuğu
    expect(out).toContain("Kira sözleşmesinin feshi");     // akan metin görünür
    expect(out).toContain("doğrulanacak");                 // GEÇİCİ rozeti (kırmızı çizgi)
  });

  it("canlı taslakta ham markdown + [src:] etiketi GÖRÜNMEZ (final'le tutarlı temiz prose)", () => {
    const out = html({
      question: "kıdem?",
      phase: "drafting",
      data: {
        kind: "answer", domain: "İş Hukuku",
        draftText: "**Kısa cevap:** Kıdem tazminatı hakkı doğar [src: m-IK-4].",
      },
    });
    expect(out).not.toContain("[src:");          // ham kaynak etiketi sızmaz
    expect(out).not.toContain("**Kısa cevap");    // literal yıldız yok → <strong> render
    expect(out).toContain("<strong>Kısa cevap:</strong>");  // bold olarak basıldı
    expect(out).toContain("Kıdem tazminatı hakkı doğar");
  });

  it("final geldiğinde ham taslak DÜŞER, doğrulanmış AnswerCard gelir", () => {
    const out = html({
      question: "x",
      phase: "final",
      data: {
        kind: "answer", domain: "Tüketici Hukuku", draftText: "eski ham taslak",
        answer: { text: "Ayıplı malda iade hakkınız vardır.", confidence: 0.9 },
        sources: [], claims: [], disclaimers: ["Genel bilgilendirme; avukata danışın."],
      },
    });
    expect(out).not.toContain("draft-stream");             // ham taslak artık yok
    expect(out).not.toContain("eski ham taslak");
    expect(out).toContain("iade hakkınız vardır");         // doğrulanmış cevap (abbr-dışı parça)
  });
});

describe("MsgActions — sesli 'Dinle' (TTS #7)", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("Dinle butonu backend TTS'i cevap metniyle çağırır + ses oynatır", async () => {
    const wav = new Blob([new Uint8Array([0x52, 0x49, 0x46, 0x46])], { type: "audio/wav" });
    const ttsSpy = vi.spyOn(api, "synthesizeTTS").mockResolvedValue(wav);
    // jsdom URL.createObjectURL / HTMLMediaElement.play implement etmez → mock
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const playSpy = vi
      .spyOn(window.HTMLMediaElement.prototype, "play")
      .mockResolvedValue(undefined);

    render(<MsgActions text="Kıdem tazminatı hakkınız doğar." onReask={() => {}} onToast={() => {}} />);
    const btn = screen.getByRole("button", { name: /dinle/i });
    fireEvent.click(btn);

    await waitFor(() => expect(ttsSpy).toHaveBeenCalledWith("Kıdem tazminatı hakkınız doğar."));
    await waitFor(() => expect(playSpy).toHaveBeenCalled());
  });

  it("TTS hatasında sessiz kalır + kullanıcıya toast (akış bozulmaz)", async () => {
    vi.spyOn(api, "synthesizeTTS").mockRejectedValue(new Error("503"));
    const onToast = vi.fn();
    render(<MsgActions text="x" onReask={() => {}} onToast={onToast} />);
    fireEvent.click(screen.getByRole("button", { name: /dinle/i }));
    await waitFor(() => expect(onToast).toHaveBeenCalled());
  });
});

describe("AttachRow — OCR düşük-güven uyarı çipi (#20)", () => {
  it("low_confidence ekli belgede 'düşük OCR güveni' uyarısı gösterir", () => {
    const out = renderToStaticMarkup(
      <AttachRow attachments={[{ filename: "belge.png", lowConf: true }]} onClear={() => {}} />,
    );
    expect(out).toContain("belge.png");
    expect(out).toContain("düşük OCR güveni");
    expect(out).toContain("low-conf");
  });

  it("temiz (yüksek-güven, PII'siz) belgede uyarı yok", () => {
    const out = renderToStaticMarkup(
      <AttachRow attachments={[{ filename: "temiz.png" }]} onClear={() => {}} />,
    );
    expect(out).not.toContain("düşük OCR güveni");
    expect(out).not.toContain("kişisel veri");
  });
});
