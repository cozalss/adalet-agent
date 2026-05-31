/* Backend AskResponse → /sor UI veri şekli dönüştürücü.

   Backend `answer` = markdown string + `[src: <source_id>]` inline tag'leri.
   UI ise `sections[].runs[]` (+ numaralı {cite:N}) + `sources[]` bekler.
   Bu modül ikisi arasındaki köprü — saf, test edilebilir, LLM'siz. */

// Cevap gövdesinin sonundaki finalize boilerplate'ini (Kaynaklar + disclaimer) kes.
const SOURCES_TAIL = /\n+-{2,}\s*\n+\*\*Kaynaklar:\*\*[\s\S]*$/;
const DISCLAIMER_TAIL = /\n*⚠️[\s\S]*$/;

// Bölüm başlıkları: **Kısa cevap:**, **Dayanak:**, **Durumuna uygulama:**, ...
const SECTION_RE = /\*\*([^*:]+):\*\*/g;
const SRC_TAG_RE = /\[src:\s*([^\]]+)\]/g;
const NUM_LI_RE = /^\s*\d+[.)]\s+(.+)$/;

// Süre/hak-kaybı riski tetikleyen anahtar kelimeler (bağlamsal uyarı).
const RISK_KEYWORDS = [
  "süre", "zamanaşımı", "zaman aşımı", "tebliğ", "tebligat",
  "duruşma", "icra", "itiraz süresi", "hak düşürücü", "bir ay içinde",
  "gün içinde", "15 gün", "30 gün", "7 gün",
];

/** citations[] → source_id'den 1-tabanlı numaraya map. */
function buildCiteMap(citations) {
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

/** citations[] → UI source kartı şekli. */
export function mapSources(citations) {
  return citations.map((c, i) => {
    const isLaw = c.doc_type === "law";
    return {
      id: i + 1,
      type: isLaw ? "Kanun" : "Yargıtay",
      badge: isLaw ? "kanun" : "yargitay",
      title: c.title || c.source_id,
      ref: c.source_id,
      passage: (c.snippet || "").trim(),
      url: c.url || "",
      verified: true,
      rel: [i + 1],
    };
  });
}

/** Markdown gövdesini bölümlere ayır → UI answer.sections[]. */
function parseSections(body, citeMap) {
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

    // "Ne yapmalı" / adım listesi → steps[]
    const lines = content.split(/\n+/).map((l) => l.trim()).filter(Boolean);
    const numbered = lines.map((l) => l.match(NUM_LI_RE)).filter(Boolean);
    if (numbered.length >= 2) {
      sections.push({
        label: h.label,
        steps: numbered.map((mm) => mm[1].replace(SRC_TAG_RE, "").trim()),
      });
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
    text:
      "Bu konuda yasal <b>süre</b> olabilir — gecikme hak kaybına yol açabilir. " +
      "İlgili belgeleri (tebligat, sözleşme) saklayın ve bir an önce bir avukata danışın.",
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
          (resp.answer || "").replace(SOURCES_TAIL, "").replace(DISCLAIMER_TAIL, "").trim() ||
          "Sorunuzu güvenilir kaynaklarla doğrulanmış şekilde yanıtlayamadım. " +
            "Yanlış bilgi vermektense bir avukata danışmanızı öneririm.",
      },
      lookedAt: citations.map((c) => c.title || c.source_id).slice(0, 5),
      conversationId: resp.conversation_id,
    };
  }

  const citeMap = buildCiteMap(citations);
  let body = (resp.answer || "").replace(SOURCES_TAIL, "").replace(DISCLAIMER_TAIL, "").trim();
  const sections = parseSections(body, citeMap);

  return {
    kind: "answer",
    domain,
    domainConfidence: typeof resp.domain_confidence === "number" ? resp.domain_confidence : null,
    sources: mapSources(citations),
    answer: { confidence: Math.round((resp.confidence || 0) * 100), sections, text: body },
    risk: deriveRisk(question, body),
    // Backend'in cevaba özel disclaimer listesi (çocuk filtresi, süre uyarısı, ...);
    // boşsa UI statik fallback gösterir.
    disclaimers: Array.isArray(resp.disclaimers) ? resp.disclaimers : [],
    conversationId: resp.conversation_id,
    // Dilekçe Ajanı bu yanıt için PDF üretti mi? (want_dilekce=true iken).
    // İndirme barı yalnız bu True iken görünür — aksi halde 404 + kırık vaat.
    hasDilekce: !!resp.has_dilekce,
  };
}

/** Netleştirme cevabını {intro, options[]} şekline ayır (numaralı sorular). */
export function mapClarify(answerText) {
  const clean = (answerText || "").replace(SOURCES_TAIL, "").replace(DISCLAIMER_TAIL, "").trim();
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
