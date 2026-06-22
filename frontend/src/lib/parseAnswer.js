/* Backend AskResponse → /sor UI veri şekli dönüştürücü.

   Backend `answer` = markdown string + `[src: <source_id>]` inline tag'leri.
   UI ise `sections[].runs[]` (+ numaralı {cite:N}) + `sources[]` bekler.
   Bu modül ikisi arasındaki köprü — saf, test edilebilir, LLM'siz. */

// Cevap gövdesinin sonundaki finalize boilerplate'ini (Kaynaklar + disclaimer) kes.
const SOURCES_TAIL = /\n+-{2,}\s*\n+\*\*Kaynaklar:\*\*[\s\S]*$/;
const DISCLAIMER_TAIL = /\n*⚠️[\s\S]*$/;
// Qwen3.5 thinking bloğu (boş <think></think> dahil) — backend akış-süzgeci kesiyor; bu
// frontend defansif yedek (kapanışlı + kapanışsız <think>).
const THINK_BLOCK = /<think>[\s\S]*?<\/think>/gi;
const THINK_OPEN = /<think>[\s\S]*$/i;

// Bölüm başlıkları: **Kısa cevap:**, **Dayanak:**, **Durumuna uygulama:**, ...
// SATIR-BAŞINA DEMİRLİ (^...gm): "1. **Sözleşmeden dönme:** ..." gibi satır-içi kalın etiketler
// bölüm başlığı SANILMASIN (aksi halde numaralı liste parçalanıp numaralar öksüz kalıyordu).
const SECTION_RE = /^[ \t]*\*\*([^*:\n]+):\*\*/gm;
const SRC_TAG_RE = /\[src:\s*([^\]]+)\]/g;
const NUM_LI_RE = /^\s*\d+[.)]\s+(.+)$/;

// Süre/hak-kaybı riski tetikleyen anahtar kelimeler (bağlamsal uyarı).
const RISK_KEYWORDS = [
  "süre", "zamanaşımı", "zaman aşımı", "tebliğ", "tebligat",
  "duruşma", "icra", "itiraz süresi", "hak düşürücü", "bir ay içinde",
  "gün içinde", "15 gün", "30 gün", "7 gün",
];

/** citations[] → source_id'den 1-tabanlı numaraya map. */
export function buildCiteMap(citations) {
  const map = new Map();
  citations.forEach((c, i) => map.set(c.source_id, i + 1));
  return map;
}

/** Bir metin parçasını runs[]'a böl: düz metin + {cite:N} işaretçileri. */
function textToRuns(text, citeMap) {
  const runs = [];
  let last = 0;
  let m;
  SRC_TAG_RE.lastIndex = 0;
  while ((m = SRC_TAG_RE.exec(text)) !== null) {
    const before = text.slice(last, m.index);
    if (before) runs.push({ t: before });
    const n = citeMap.get(m[1].trim());
    if (n != null) runs.push({ cite: n });
    last = m.index + m[0].length;
  }
  const tail = text.slice(last);
  if (tail) runs.push({ t: tail });
  return runs.length ? runs : [{ t: text }];
}

/** Bölüm içeriğini SIRALI bloklara böl: ardışık numaralı satırlar → {steps}, diğer metin → {runs}.
 *  Karışık içerikte (numaralı liste + öncesinde/sonrasında açıklama paragrafı) hiçbir şey DÜŞMEZ. */
function parseContentBlocks(content, citeMap) {
  const blocks = [];
  let prose = [];
  let steps = [];
  const flushProse = () => {
    const t = prose.join("\n").trim();
    if (t) blocks.push({ runs: textToRuns(t, citeMap) });
    prose = [];
  };
  const flushSteps = () => {
    if (steps.length) blocks.push({ steps: steps.slice() });
    steps = [];
  };
  for (const line of content.split("\n")) {
    const mm = line.match(NUM_LI_RE);
    if (mm) { flushProse(); steps.push(mm[1].replace(SRC_TAG_RE, "").trim()); }
    else { flushSteps(); prose.push(line); }
  }
  flushSteps();
  flushProse();
  return blocks;
}

/** citations[] → UI source kartı şekli. */
/** Emsal/mevzuat önizleme snippet'ini temizle — "madde yarısından başlıyor / sonu yok" görünümünü
 *  düzeltir. Korpus chunk'ı keyfi ~1400 krk pencere → kelime/cümle ORTASINDAN kesilir. Baş küçük
 *  harfle (cümle-ortası) başlıyorsa yarım token'ı düşür + "…"; sonu yarımsa cümle sınırında kes + "…".
 *  Salt görsel: içeriği değiştirmez, yalnız kırık kenarları kırpar. Tam metin tıklamada gelir. */
export function cleanLegalSnippet(raw, maxLen = 360) {
  let s = (raw || "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  const f = s[0];
  // Baş cümle-ortası (küçük harf) → ilk yarım token'ı düşür + "…"
  if (f === f.toLocaleLowerCase("tr") && f !== f.toLocaleUpperCase("tr")) {
    const sp = s.indexOf(" ");
    if (sp > 0 && sp <= 24) s = s.slice(sp + 1).trimStart();
    s = "… " + s;
  }
  // Son: uzunsa son TAM cümlede kes; yarım bitiyorsa "…"
  if (s.length > maxLen) {
    const cut = s.slice(0, maxLen);
    const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "), cut.lastIndexOf("! "));
    s = (end > maxLen * 0.5 ? cut.slice(0, end + 1) : cut.replace(/\s+\S*$/, "")).trim() + " …";
  } else if (!/[.!?"”)\]]$/.test(s)) {
    s = s + " …";
  }
  return s.trim();
}

export function mapSources(citations) {
  return citations.map((c, i) => {
    const isLaw = c.doc_type === "law";
    return {
      id: i + 1,
      type: isLaw ? "Kanun" : "Yargıtay",
      badge: isLaw ? "kanun" : "yargitay",
      title: c.title || c.source_id,
      ref: c.source_id,
      passage: cleanLegalSnippet(c.snippet || ""),
      // Tam madde metni (baştan) — Kaynaklar paneli "tam maddeyi göster" ile açar (fetch yok;
      // kanun chunk'ı zaten ~tam madde). passage kısa önizleme, fullText tam.
      fullText: cleanLegalSnippet(c.snippet || "", 1600),
      url: c.url || "",
      verified: true,
      rel: [i + 1],
    };
  });
}

/** Markdown gövdesini bölümlere ayır → UI answer.sections[]. */
export function parseSections(body, citeMap) {
  // Başlık konumlarını bul
  const heads = [];
  let m;
  SECTION_RE.lastIndex = 0;
  while ((m = SECTION_RE.exec(body)) !== null) {
    heads.push({ label: m[1].trim(), start: m.index, contentStart: m.index + m[0].length });
  }
  if (heads.length === 0) {
    // Başlık yok → tek lead bölüm
    return [{ label: "Cevap", lead: true, runs: textToRuns(body.trim(), citeMap) }];
  }
  const sections = [];
  for (let i = 0; i < heads.length; i++) {
    const h = heads[i];
    const end = i + 1 < heads.length ? heads[i + 1].start : body.length;
    const content = body.slice(h.contentStart, end).trim();
    const lower = h.label.toLocaleLowerCase("tr");
    const isLead = i === 0 || lower.includes("kısa cevap");

    // Numaralı liste içeren bölüm → SIRALI bloklar (liste + çevresindeki açıklama prose'u korunur,
    // düşmez). Sade durumda (yalnız liste) eski {steps} şekliyle uyumlu kalır.
    const numberedCount = content.split("\n").filter((l) => NUM_LI_RE.test(l)).length;
    if (numberedCount >= 2) {
      const blocks = parseContentBlocks(content, citeMap);
      if (blocks.length === 1 && blocks[0].steps) {
        sections.push({ label: h.label, steps: blocks[0].steps });
      } else {
        sections.push({ label: h.label, blocks });
      }
      continue;
    }
    sections.push({ label: h.label, lead: isLead, runs: textToRuns(content, citeMap) });
  }
  return sections;
}

/** Süre/tebligat gibi risk kelimesi varsa bağlamsal uyarı üret (yoksa null). */
export function deriveRisk(question, answer) {
  const hay = ((question || "") + " " + (answer || "")).toLocaleLowerCase("tr");
  const hit = RISK_KEYWORDS.find((k) => hay.includes(k));
  if (!hit) return null;
  return {
    keyword: hit,
    // Markdown (**kalın**) — RiskWarning renderInline ile basar (HTML değil, XSS yok).
    // NOT: "avukata danışın" TEKRARI bilinçli KALDIRILDI — DisclaimerBar zaten aynı mesajı
    // basıyor; aynı cevapta üç kat "avukata danışın" = gereksiz/paternalist tekrar (Anthropic
    // Constitution: "excessive warnings/caveats that aren't necessary"). Burada SADECE risk-spesifik
    // KATMA-DEĞER kalır (aciliyet + somut belge saklama); genel disclaimer'ı bar üstlenir.
    text:
      "Bu konuda yasal **süre** olabilir — gecikme hak kaybına yol açabilir. " +
      "İlgili belgeleri (tebligat, sözleşme) saklayın ve gecikmeden harekete geçin.",
  };
}

/**
 * Tam AskResponse → UI turn data.
 * @returns {{kind:"answer"|"reject", domain:string, sources:any[], answer?:any, risk?:any, reject?:any, lookedAt?:string[], conversationId?:string, hasDilekce?:boolean}}
 */
export function mapResponse(resp, question) {
  const domain = DOMAIN_LABELS[resp.domain] || resp.domain || "";
  const citations = resp.citations || [];

  if (resp.verdict === "reject") {
    return {
      kind: "reject",
      domain,
      reject: {
        title: "Bu konuda emin değilim",
        body:
          stripAnswerTail(resp.answer) ||
          "Sorunuzu güvenilir kaynaklarla doğrulanmış şekilde yanıtlayamadım. " +
            "Yanlış bilgi vermektense bir avukata danışmanızı öneririm.",
      },
      // CLAUDE.md §2: reddedilen yanıt da hukuki disclaimer taşımalı. stripAnswerTail
      // gövdedeki ⚠️ kuyruğunu sildiğinden, backend disclaimers'ı AYRI taşıyıp UI'da
      // DisclaimerBar'a veririz (gerçek verify-reject'te backend [DISCLAIMER_TR] gönderir).
      disclaimers: Array.isArray(resp.disclaimers) ? resp.disclaimers : [],
      lookedAt: citations.map((c) => c.title || c.source_id).slice(0, 5),
      conversationId: resp.conversation_id,
    };
  }

  // "Kaynak" = cevabın GERÇEKTEN cite ettiği kaynaklar (sabit retrieval havuzu '16' DEĞİL —
  // her cevapta aynı '16' yanıltıcıydı: havuz 8 mevzuat + 8 emsal aday, çoğu kullanılmıyor).
  // claims.cite_ids = gövdedeki [src:] referansları. citeMap de buradan kurulur → inline [N]
  // numaraları + panel + sayı TUTARLI. Boşsa (nadir: cite'siz fuzzy-verified) havuza düş ('0' gösterme).
  const usedIds = new Set();
  (resp.claims || []).forEach((c) => (c.cite_ids || []).forEach((id) => usedIds.add(id)));
  const usedCitations = usedIds.size ? citations.filter((c) => usedIds.has(c.source_id)) : citations;

  const citeMap = buildCiteMap(usedCitations);
  const body = stripAnswerTail(resp.answer);
  const sections = parseSections(body, citeMap);
  const mappedSources = mapSources(usedCitations);
  // İlgili Kararlar: GETİRİLEN tüm emsal kararlar. Cevap gövdesi genelde kanun maddesi
  // cite eder, emsalı CITE ETMEZ (8 emsal getirilip 0'ı cite ediliyordu) → usedCitations'a
  // güvenme; FULL citations'tan al. Aynı kararın farklı chunk'ları başlıkla teklenir.
  const _seenCase = new Set();
  const caseCitations = (citations || []).filter((c) => {
    if ((c.doc_type || "") === "law") return false;
    const key = (c.title || c.source_id || "").trim().toLowerCase();
    if (!key || _seenCase.has(key)) return false;
    _seenCase.add(key);
    return true;
  });

  return {
    kind: "answer",
    domain,
    domainConfidence: typeof resp.domain_confidence === "number" ? resp.domain_confidence : null,
    sources: mappedSources,
    // Emsal (mahkeme kararları) ayrı yüzeye çıkar: kanun maddeleriyle karışmadan,
    // "İlgili Kararlar" stat'ı + bölümü + yan panelde gösterilir (cite edilmese de).
    relatedCases: mapSources(caseCitations),
    // Retrieval havuzu boyutu (corpus'tan taranan aday) — şeffaflık: "N tarandı, M kullanıldı".
    scannedCount: citations.length,
    answer: { confidence: Math.round((resp.confidence || 0) * 100), sections, text: body },
    risk: deriveRisk(question, body),
    // Backend'in cevaba özel disclaimer listesi (çocuk filtresi, süre uyarısı, ...);
    // boşsa UI statik fallback gösterir.
    disclaimers: Array.isArray(resp.disclaimers) ? resp.disclaimers : [],
    // Doğrulama Ajanı'nın iddia-bazlı çıktısı (şeffaflık paneli) — cite_ids
    // (source_id) UI'ın 1-tabanlı numaralarına çevrilir.
    claims: mapClaims(resp.claims, citeMap),
    lookedAt: citations.map((c) => c.title || c.source_id).slice(0, 8),
    debateNotes: (resp.debate_notes || "").trim(),
    retryCount: Number(resp.retry_count) || 0,
    // Tahmin Ajanı (8. ajan) — opsiyonel; yoksa null. Disclaimer zorunlu.
    prediction: mapPrediction(resp.prediction),
    conversationId: resp.conversation_id,
    // Dilekçe Ajanı bu yanıt için PDF üretti mi? (want_dilekce=true iken).
    // İndirme barı yalnız bu True iken görünür — aksi halde 404 + kırık vaat.
    hasDilekce: !!resp.has_dilekce,
  };
}

/** Backend claims[] → UI şeffaflık panel şekli (cite_ids → 1-tabanlı numara). */
function mapClaims(claims, citeMap) {
  if (!Array.isArray(claims)) return [];
  return claims.map((c) => ({
    text: c.text || "",
    verified: !!c.verified,
    score: Math.round((Number(c.verify_score) || 0) * 100),
    reason: c.verify_reason || "",
    citeNums: (c.cite_ids || []).map((id) => citeMap.get(id)).filter((n) => n != null),
  }));
}

/** Backend prediction → UI tahmin kartı şekli (null → gösterilmez). */
function mapPrediction(p) {
  if (!p || !p.verdict_class) return null;
  return {
    verdictClass: p.verdict_class,
    confidence: Math.round((Number(p.confidence) || 0) * 100),
    similarCaseIds: Array.isArray(p.similar_case_ids) ? p.similar_case_ids : [],
    reasoning: p.reasoning || "",
    disclaimer: p.disclaimer || "",
  };
}

/** Netleştirme cevabını {intro, options[]} şekline ayır.
 *  Backend yapısal `clarifying_questions` listesi verdiyse onu DOĞRUDAN kullan —
 *  markdown regex ayrıştırmasına bağımlı kalma (tek-soruluk round-2 follow-up'ta
 *  bile güvenilir; eski heuristik `>=2 numaralı satır` şartında patlıyordu). */
export function mapClarify(answerText, questions) {
  if (Array.isArray(questions) && questions.length) {
    const options = questions.map((q) => String(q).trim()).filter(Boolean);
    if (options.length) {
      return { intro: "Size daha doğru yardımcı olabilmem için birkaç şeyi netleştirelim:", options };
    }
  }
  const clean = stripAnswerTail(answerText);
  const lines = clean.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const options = [];
  let intro = "";
  for (const line of lines) {
    const m = line.match(/^\s*\d+[.)]\s+(.+)$/) || line.match(/^[-•]\s+(.+)$/);
    if (m) options.push(m[1].trim());
    else if (!intro && !options.length) intro = line;
  }
  return {
    intro: intro || "Size daha iyi yardımcı olabilmem için birkaç şeyi netleştirelim:",
    options: options.length ? options : ["Durumunuzu biraz daha ayrıntılı anlatır mısınız?"],
  };
}

/** Smalltalk/redirect = hafif sohbet yanıtı mı? (soğuk RejectCard değil, baloncuk).
 *  Önce backend'in kesin sinyali response_intent; yoksa (eski/geçmiş yanıt) heuristik. */
export function looksSmalltalk(resp) {
  const i = resp.response_intent;
  if (i) return i === "chat" || i === "smalltalk" || i === "redirect" || i === "out_of_scope_sensitive";
  return resp.verdict === "pass"
    && (resp.confidence || 0) >= 0.99
    && (resp.citations || []).length === 0
    && (resp.disclaimers || []).length === 0
    && resp.domain === "unknown";
}

/** Cevap gövdesinden finalize kuyruğunu (Kaynaklar listesi + ⚠️ disclaimer) kes.
 *  ORTAK: hem final (mapSmalltalk) hem CANLI streaming (App akan baloncuk) kullanır →
 *  streaming ile final AYNI temiz metni gösterir (LLM kendi disclaimer'ını eklese bile
 *  akış sırasında görünüp final'de kaybolmaz = içerik-flip önlenir). */
export function stripAnswerTail(text) {
  return (text || "")
    .replace(THINK_BLOCK, "")
    .replace(THINK_OPEN, "")
    .replace(SOURCES_TAIL, "")
    .replace(DISCLAIMER_TAIL, "")
    .trim();
}

/** CANLI taslak metnini ekrana basmadan önce temizle (DraftStreamBubble).
 *
 *  Sorun: ham draft `**Kısa cevap:**` markdown'ı + `[src: m-IK-4]` kaynak etiketleri
 *  içerir; bunlar final kartta parse edilip cilalanır ama canlı baloncukta OLDUĞU GİBİ
 *  görünüyordu (literal yıldız + sızıntı gibi tag) → bozuk/tutarsız his, sonra bambaşka
 *  karta sıçrama. Bu fonksiyon taslağı final ile AYNI temiz prose'a indirir:
 *    • finalize kuyruğu (stripAnswerTail) + `[src:..]` etiketleri kaldırılır (final numaralı
 *      çip ekleyecek — taslakta numara henüz yok, gizle),
 *    • STREAMING guard: sonda kapanmamış `**` (yarım başlık) ve yarım `[..` etiketi gizlenir
 *      (token token gelirken "**Kısa cev" gibi çirkin flaş olmasın).
 *  Markdown **kalın** korunur → DraftStreamBubble renderInline ile bold basar (final'le tutarlı). */
// cleanDraftText'e ÖZEL (paylaşılan global SRC_TAG_RE'nin lastIndex'ini bozmamak için
// ayrı literal — bu fonksiyon her stream token'ında çağrılır, textToRuns exec-loop'uyla
// aynı obje paylaşılmamalı).
const SRC_TAG_CLEAN_RE = /\[src:\s*[^\]]+\]/g;

export function cleanDraftText(text) {
  let t = stripAnswerTail(text);
  t = t.replace(SRC_TAG_CLEAN_RE, "");     // tam [src: id] etiketleri (kendi regex'i)
  t = t.replace(/\[[^\]]*$/, "");          // sonda kapanmamış [..  (yarım stream tag)
  // Sonda kapanmamış ** (tek sayıda) → son **'ten sonrasını gizle (yarım başlık flaşını önle)
  if (((t.match(/\*\*/g) || []).length) % 2 === 1) {
    t = t.slice(0, t.lastIndexOf("**"));
  }
  return t
    .replace(/[ \t]*\*$/, "")              // sonda kalan tek * (yarım italik)
    .replace(/ {2,}/g, " ")                // tag silindikten sonra çift boşluk
    .replace(/\s+([.,;:])/g, "$1")         // " ." → "." (tag öncesi boşluk)
    .trimEnd();
}

/** Smalltalk/redirect yanıtını hafif baloncuk şekline indir (kaynak/disclaimer kuyruğu
 *  gövdeden silinir; disclaimer varsa AYRI taşınır → UI tek otorite DisclaimerBar'da basar,
 *  gövdeye gömülü "akışta-var-final'de-yok" flip'i önlenir). Saf selam → liste boş → bar yok. */
export function mapSmalltalk(resp) {
  return {
    kind: "smalltalk",
    domain: "",
    smalltalk: { text: stripAnswerTail(resp.answer) },
    disclaimers: Array.isArray(resp.disclaimers) ? resp.disclaimers : [],
  };
}

const DOMAIN_LABELS = {
  tuketici: "Tüketici Hukuku",
  isHukuku: "İş Hukuku",
  kira: "Kira Hukuku",
  icra: "İcra Hukuku",
  trafik: "Trafik Hukuku",
  vergi: "Vergi Hukuku",
  tapu: "Tapu / Gayrimenkul",
  idari: "İdari Hukuk",
  unknown: "Belirsiz",
};
