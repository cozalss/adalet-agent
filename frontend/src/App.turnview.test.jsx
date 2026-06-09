/* TurnView render testleri — özellikle KIRMIZI ÇİZGİ (CLAUDE.md §2): reject yolundaki
   yanıt da hukuki disclaimer taşımalı. Denetim bulgusu #1 (2026-06-09 worldclass-audit).
   + MsgActions sesli "Dinle" (#7). */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { TurnView, MsgActions } from "./App.jsx";
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
