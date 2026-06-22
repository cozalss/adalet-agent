/* parseAnswer — backend AskResponse → /sor UI veri şekli (SSE→UI köprüsü) testleri. */
import { describe, it, expect } from "vitest";
import { mapResponse, mapClarify, mapSources, deriveRisk, looksSmalltalk, mapSmalltalk, cleanDraftText, parseSections } from "./parseAnswer.js";

describe("parseSections — satır-içi kalın etiket bölüm SANILMAZ (öksüz-numara fix)", () => {
  it("numaralı + kalın-etiketli seçenek listesini TEK bölüm yapar (öksüz numara yok)", () => {
    const body = [
      "**Kısa cevap:** Evet, iade hakkınız var.",
      "",
      "**Seçenekleriniz:**",
      "1. **Sözleşmeden dönme:** Malı iade edip sözleşmeden dönebilirsiniz.",
      "2. **Bedel indirimi:** Ayıp oranında indirim isteyebilirsiniz.",
      "3. **Onarım:** Malın onarılmasını talep edebilirsiniz.",
    ].join("\n");
    const secs = parseSections(body, new Map());
    const labels = secs.map((s) => s.label);
    expect(labels).not.toContain("Sözleşmeden dönme");
    expect(labels).not.toContain("Bedel indirimi");
    expect(labels).toEqual(["Kısa cevap", "Seçenekleriniz"]);
    const sec = secs.find((s) => s.label === "Seçenekleriniz");
    expect(sec.steps).toHaveLength(3); // sade liste → {steps}
    expect(sec.steps[0]).toContain("Sözleşmeden dönme");
  });

  it("liste + SONRASINDA açıklama paragrafı → bloklar; açıklama DÜŞMEZ", () => {
    const body = [
      "**Seçenekleriniz:**",
      "1. **Sözleşmeden dönme:** Malı iade edebilirsiniz.",
      "2. **Bedel indirimi:** İndirim isteyebilirsiniz.",
      "",
      "Bu hakları kullanmak için satıcıya yazılı bildirimde bulunmanız önemlidir.",
    ].join("\n");
    const sec = parseSections(body, new Map()).find((s) => s.label === "Seçenekleriniz");
    expect(sec.blocks).toBeTruthy();
    const stepsBlock = sec.blocks.find((b) => b.steps);
    const proseBlock = sec.blocks.find((b) => b.runs);
    expect(stepsBlock.steps).toHaveLength(2);
    // trailing açıklama korunmalı (eski steps-render'da DÜŞÜYORDU)
    const proseText = proseBlock.runs.map((r) => r.t || "").join("");
    expect(proseText).toContain("yazılı bildirimde");
  });

  it("gerçek satır-başı başlıkları bölüm olarak ayırır (regresyon yok)", () => {
    const labels = parseSections("**Kısa cevap:** X.\n\n**Dayanak:** Madde Y der.", new Map()).map((s) => s.label);
    expect(labels).toEqual(["Kısa cevap", "Dayanak"]);
  });
});

describe("cleanDraftText — CANLI taslak temizliği (saçmalık fix)", () => {
  it("ham [src: id] kaynak etiketlerini kaldırır (final numaralı çip ekler)", () => {
    const out = cleanDraftText("İş Kanunu geçici 6. madde [src: m-IK-4] uygulanır.");
    expect(out).not.toContain("[src:");
    expect(out).toContain("geçici 6. madde uygulanır.");  // boşluk normalize
  });

  it("birden çok kaynak etiketini temizler + çift boşluk bırakmaz", () => {
    const out = cleanDraftText("a [src: x] b [src: y] c");
    expect(out).toBe("a b c");
  });

  it("STREAMING guard: sonda kapanmamış ** (yarım başlık) gizlenir", () => {
    // "**Kısa cevap:** ... **Durumun" → yarım ikinci başlık flaşı görünmemeli
    const out = cleanDraftText("**Kısa cevap:** metin\n\n**Durumun");
    expect(out).toContain("**Kısa cevap:**");        // tamamlanmış başlık korunur (renderInline bold yapar)
    expect(out).not.toContain("**Durumun");          // yarım başlık gizlendi
  });

  it("STREAMING guard: sonda yarım [src: etiketi gizlenir", () => {
    const out = cleanDraftText("madde uygulanır [src: m-IK");
    expect(out).not.toContain("[src:");
    expect(out).toContain("madde uygulanır");
  });

  it("tamamlanmış **kalın** korunur (renderInline'a bırakılır, literal yıldız final'le tutarlı)", () => {
    expect(cleanDraftText("**Dayanak:** İş Kanunu")).toBe("**Dayanak:** İş Kanunu");
  });

  it("finalize kuyruğunu (Kaynaklar + disclaimer) da keser", () => {
    const out = cleanDraftText("Cevap.\n\n---\n**Kaynaklar:**\n- x\n\n⚠️ uyarı");
    expect(out).toBe("Cevap.");
  });
});

describe("looksSmalltalk — selam/yönlendirme ayrımı", () => {
  it("response_intent ile kesin ayırır", () => {
    expect(looksSmalltalk({ response_intent: "smalltalk" })).toBe(true);
    expect(looksSmalltalk({ response_intent: "redirect" })).toBe(true);
    expect(looksSmalltalk({ response_intent: "out_of_scope_sensitive" })).toBe(true);
    expect(looksSmalltalk({ response_intent: "legal_answer" })).toBe(false);
    expect(looksSmalltalk({ response_intent: "needs_clarification" })).toBe(false);
  });
  it("response_intent yoksa (eski yanıt) heuristik imza", () => {
    expect(looksSmalltalk({ verdict: "pass", confidence: 1, citations: [], disclaimers: [], domain: "unknown" })).toBe(true);
    expect(looksSmalltalk({ verdict: "pass", confidence: 0.7, citations: [{}], disclaimers: ["x"], domain: "kira" })).toBe(false);
  });
  it("mapSmalltalk: kaynak/disclaimer kuyruğunu siler", () => {
    const r = mapSmalltalk({ answer: "Merhaba!\n\n---\n**Kaynaklar:**\n- x\n\n⚠️ disclaimer" });
    expect(r.kind).toBe("smalltalk");
    expect(r.smalltalk.text).toBe("Merhaba!");
  });
});

describe("mapResponse — answer", () => {
  const resp = {
    domain: "kira",
    verdict: "pass",
    confidence: 0.88,
    answer: "**Kısa cevap:** Yasal sınır TÜFE'dir [src: tbk-344].\n\n**Dayanak:** TBK madde 344.",
    citations: [{ source_id: "tbk-344", doc_type: "law", title: "TBK m.344", snippet: "madde metni" }],
    disclaimers: ["Hukuki tavsiye değildir."],
    has_dilekce: false,
    conversation_id: "c1",
  };

  it("kind=answer + domain etiketi + güven %", () => {
    const out = mapResponse(resp, "ev sahibim zam istiyor");
    expect(out.kind).toBe("answer");
    expect(out.domain).toBe("Kira Hukuku");
    expect(out.answer.confidence).toBe(88);
    expect(out.conversationId).toBe("c1");
    expect(out.hasDilekce).toBe(false);
    expect(out.disclaimers).toEqual(["Hukuki tavsiye değildir."]);
  });

  it("başlıkları bölümlere ayırır (Kısa cevap + Dayanak)", () => {
    const out = mapResponse(resp, "");
    const labels = out.answer.sections.map((s) => s.label);
    expect(labels).toContain("Kısa cevap");
    expect(labels).toContain("Dayanak");
    expect(out.answer.sections[0].lead).toBe(true);
  });

  it("[src: id] etiketini 1-tabanlı {cite:N} run'a çevirir", () => {
    const out = mapResponse(resp, "");
    const runs = out.answer.sections[0].runs;
    expect(runs.some((r) => r.cite === 1)).toBe(true);
    // ham [src:...] metinde kalmamalı
    expect(JSON.stringify(runs)).not.toContain("src:");
  });

  it("citations → kaynak kartları (kanun)", () => {
    const out = mapResponse(resp, "");
    expect(out.sources[0]).toMatchObject({
      id: 1, type: "Kanun", badge: "kanun", title: "TBK m.344", verified: true,
    });
  });

  it("relatedCases: emsal (case) kararlarını ayrı yüzeye çıkarır", () => {
    const r = {
      domain: "kira", verdict: "pass", confidence: 0.8, answer: "**Kısa cevap:** X.",
      citations: [
        { source_id: "tbk-350", doc_type: "law", title: "TBK m.350", snippet: "madde" },
        { source_id: "y-3hd-1", doc_type: "case", title: "Yargıtay 3. HD 2023/123", snippet: "karar özeti", url: "u" },
      ],
    };
    const out = mapResponse(r, "");
    expect(out.sources).toHaveLength(2);                 // hepsi kaynak panelinde
    expect(out.relatedCases).toHaveLength(1);            // yalnız emsal ayrı bölümde
    expect(out.relatedCases[0]).toMatchObject({ type: "Yargıtay", badge: "yargitay", title: "Yargıtay 3. HD 2023/123" });
  });

  it("relatedCases: emsal yoksa boş dizi (bölüm render edilmez)", () => {
    expect(mapResponse(resp, "").relatedCases).toEqual([]);  // resp yalnız kanun içeriyor
  });

  it("relatedCases: cite EDİLMEYEN emsal da gösterilir + aynı başlık teklenir", () => {
    // Gerçek davranış: cevap kanun cite eder, emsalı CITE ETMEZ (8 getirilip 0 cite).
    // relatedCases usedCitations'tan DEĞİL, getirilen TÜM emsaldan gelir.
    const r = {
      domain: "kira", verdict: "pass", confidence: 0.8,
      answer: "**Kısa cevap:** TÜFE [src: tbk-344].",
      citations: [
        { source_id: "tbk-344", doc_type: "law", title: "TBK m.344", snippet: "m" },
        { source_id: "y-1", doc_type: "case", title: "Yargıtay 3.HD 2011/1", snippet: "k", url: "u1" },
        { source_id: "y-2", doc_type: "case", title: "Yargıtay 3.HD 2011/1", snippet: "k", url: "u2" },
        { source_id: "y-3", doc_type: "case", title: "Yargıtay 6.HD 2025/9", snippet: "k", url: "u3" },
      ],
      claims: [{ text: "x", cite_ids: ["tbk-344"], verified: true }],
    };
    const out = mapResponse(r, "");
    expect(out.sources).toHaveLength(1);        // yalnız cite edilen kanun
    expect(out.relatedCases).toHaveLength(2);   // 3 emsal → başlıkla teklenip 2
    expect(out.relatedCases.map((c) => c.title)).toEqual(["Yargıtay 3.HD 2011/1", "Yargıtay 6.HD 2025/9"]);
  });

  it("Kaynak = cevabın CITE ETTİĞİ kaynaklar (sabit retrieval havuzu değil)", () => {
    // Havuz 4 aday AMA cevap yalnız 2 madde cite ediyor → sources 2 olmalı ('16 saçma' fix).
    const r = {
      domain: "kira", verdict: "pass", confidence: 0.7,
      answer: "**Kısa cevap:** TÜFE sınırı [src: m-TBK-344]. Dava [src: m-TBK-345].",
      citations: [
        { source_id: "m-TBK-344", doc_type: "law", title: "TBK 344", snippet: "x" },
        { source_id: "m-TBK-345", doc_type: "law", title: "TBK 345", snippet: "y" },
        { source_id: "m-TBK-321", doc_type: "law", title: "TBK 321", snippet: "z" },
        { source_id: "h-999-c1", doc_type: "case", title: "Yargıtay", snippet: "w" },
      ],
      claims: [
        { text: "TÜFE sınırı", cite_ids: ["m-TBK-344"], verified: true },
        { text: "Dava açılır", cite_ids: ["m-TBK-345"], verified: true },
      ],
    };
    const out = mapResponse(r, "");
    expect(out.sources).toHaveLength(2);                       // 4 değil → cite edilen 2
    expect(out.sources.map((s) => s.ref).sort()).toEqual(["m-TBK-344", "m-TBK-345"]);
    // inline numaralar cited-listeye göre tutarlı remap (kopuk numara yok)
    const runs = out.answer.sections[0].runs;
    expect(runs.some((x) => x.cite === 1)).toBe(true);
    expect(JSON.stringify(runs)).not.toContain("src:");
  });

  it("claim cite_ids boşsa → havuza düşer ('0 Kaynak' gösterme)", () => {
    const r = {
      domain: "kira", verdict: "pass", confidence: 0.7,
      answer: "**Kısa cevap:** Genel bilgi.",
      citations: [{ source_id: "m-TBK-344", doc_type: "law", title: "TBK 344", snippet: "x" }],
      claims: [{ text: "Genel bilgi", cite_ids: [], verified: true }],
    };
    const out = mapResponse(r, "");
    expect(out.sources).toHaveLength(1);  // fallback: havuz
  });

  it("Kaynaklar/disclaimer kuyruğunu gövdeden kırpar", () => {
    const r = { ...resp, answer: "**Kısa cevap:** X.\n\n--\n\n**Kaynaklar:**\n1. TBK\n\n⚠️ uyarı" };
    const out = mapResponse(r, "");
    expect(out.answer.text).not.toContain("Kaynaklar");
    expect(out.answer.text).not.toContain("⚠️");
  });

  it("numaralı 'ne yapmalı' listesini steps[]'e çevirir", () => {
    const r = { ...resp, answer: "**Ne yapmalı:**\n1. İhtarname gönder\n2. Dava aç" };
    const out = mapResponse(r, "");
    const step = out.answer.sections.find((s) => s.steps);
    expect(step.steps).toEqual(["İhtarname gönder", "Dava aç"]);
  });

  it("claims → şeffaflık şekli (cite_ids → numara, score %)", () => {
    const r = { ...resp, claims: [{ text: "iddia", verified: true, verify_score: 0.9, cite_ids: ["tbk-344"] }] };
    const out = mapResponse(r, "");
    expect(out.claims[0]).toMatchObject({ text: "iddia", verified: true, score: 90, citeNums: [1] });
  });

  it("prediction → tahmin kartı şekli (null güvenli)", () => {
    const r = { ...resp, prediction: { verdict_class: "kazandi", confidence: 0.7, similar_case_ids: ["a"], disclaimer: "d" } };
    const out = mapResponse(r, "");
    expect(out.prediction).toMatchObject({ verdictClass: "kazandi", confidence: 70, similarCaseIds: ["a"], disclaimer: "d" });
    expect(mapResponse(resp, "").prediction).toBeNull();
  });
});

describe("mapResponse — reject", () => {
  it("kind=reject + body + bakılan kaynaklar", () => {
    const out = mapResponse({
      domain: "unknown", verdict: "reject", answer: "Emin değilim.",
      citations: [{ title: "X", source_id: "x" }, { title: "Y", source_id: "y" }],
    });
    expect(out.kind).toBe("reject");
    expect(out.reject.body).toContain("Emin değilim");
    expect(out.lookedAt).toEqual(["X", "Y"]);
  });

  it("boş cevapta anlamlı fallback body", () => {
    const out = mapResponse({ verdict: "reject", answer: "", citations: [] });
    expect(out.reject.body).toContain("avukat");
  });

  it("reject yolu backend disclaimer'larını taşır (KIRMIZI ÇİZGİ §2: her yanıtta disclaimer)", () => {
    const out = mapResponse({
      domain: "isHukuku", verdict: "reject", answer: "Doğrulayamadım.",
      disclaimers: ["Hukuki tavsiye değildir."], citations: [],
    });
    expect(out.disclaimers).toEqual(["Hukuki tavsiye değildir."]);
  });

  it("reject'te disclaimers yoksa [] (transport-hata vb. bar fallback'e düşer)", () => {
    const out = mapResponse({ verdict: "reject", answer: "", citations: [] });
    expect(out.disclaimers).toEqual([]);
  });
});

describe("mapClarify", () => {
  it("numaralı seçenekleri + intro ayırır", () => {
    const out = mapClarify("Şunları netleştirelim:\n1. Kira ne kadar?\n2. Sözleşme var mı?");
    expect(out.intro).toBe("Şunları netleştirelim:");
    expect(out.options).toEqual(["Kira ne kadar?", "Sözleşme var mı?"]);
  });
  it("madde işaretli (-•) seçenekleri de tanır", () => {
    expect(mapClarify("- A\n- B").options).toEqual(["A", "B"]);
  });
  it("boş girdide fallback intro + seçenek", () => {
    const out = mapClarify("");
    expect(out.intro).toMatch(/netleştir/i);
    expect(out.options).toHaveLength(1);
  });
  it("yapısal clarifying_questions verilince markdown yerine onu kullanır", () => {
    const out = mapClarify("alakasız markdown gövde", ["Hangi sebeple?", "Sözleşme yazılı mı?"]);
    expect(out.options).toEqual(["Hangi sebeple?", "Sözleşme yazılı mı?"]);
    expect(out.intro).toMatch(/netleştir/i);
  });
  it("tek yapısal soru (round-2 follow-up) da güvenilir döner", () => {
    expect(mapClarify("", ["Konutta kim oturacak?"]).options).toEqual(["Konutta kim oturacak?"]);
  });
  it("boş yapısal liste → markdown ayrıştırmasına düşer", () => {
    expect(mapClarify("1. A\n2. B", []).options).toEqual(["A", "B"]);
  });
});

describe("mapSources", () => {
  it("law→Kanun, case→Yargıtay; alanları doldurur", () => {
    const out = mapSources([
      { doc_type: "law", title: "TBK m.1", source_id: "a", snippet: "s", url: "u" },
      { doc_type: "case", title: "Y 9.HD", source_id: "b" },
    ]);
    expect(out[0]).toMatchObject({ id: 1, type: "Kanun", badge: "kanun", ref: "a", url: "u", verified: true });
    expect(out[1]).toMatchObject({ id: 2, type: "Yargıtay", badge: "yargitay" });
  });
  it("title yoksa source_id kullanır", () => {
    expect(mapSources([{ doc_type: "law", source_id: "x" }])[0].title).toBe("x");
  });

});

describe("deriveRisk", () => {
  it("süre/itiraz gibi anahtar kelimede uyarı üretir", () => {
    const r = deriveRisk("itiraz süresi", "30 gün içinde başvurun");
    expect(r).not.toBeNull();
    expect(r.text).toContain("süre");
  });
  it("DisclaimerBar ile çift 'avukata danışın' üretmez (gereksiz tekrar yok)", () => {
    const r = deriveRisk("itiraz süresi", "30 gün içinde başvurun");
    // Anthropic anti-paternalist ilke: aynı cevapta tekrar disclaimer = gereksiz caveat.
    expect(r.text.toLocaleLowerCase("tr")).not.toContain("avukat");
    // Risk-spesifik katma-değer korunur (aciliyet + belge saklama).
    expect(r.text).toContain("hak kaybı");
    expect(r.text).toContain("belgeleri");
  });
  it("risk kelimesi yoksa null", () => {
    expect(deriveRisk("merhaba", "nasılsın")).toBeNull();
  });
});
