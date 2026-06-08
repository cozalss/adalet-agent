/* Ajan Akış Şeması — SAF veri + saf fonksiyon (React import YOK → Vitest unit-test).
   Backend SSE'den (node.active_node + faz event'leri) düğüm-durumu türetir.
   RED-LINE: yalnız ilerleme görselleştirir; doğrulama SONUCU üretmez (o backend'de). */

// 7 çekirdek ajan — sabit DAG. col=yatay sütun, row=dikey satır (mevzuat∥emsal çatallı).
export const NODES = [
  { id: "triaj", label: "Triaj", sub: "alan + niyet", col: 0, row: 1 },
  { id: "mevzuat", label: "Mevzuat", sub: "kanun maddeleri", col: 1, row: 0 },
  { id: "emsal", label: "Emsal", sub: "Yargıtay/Danıştay", col: 1, row: 2 },
  { id: "draft", label: "Taslak", sub: "kaynaklı cevap", col: 2, row: 1 },
  { id: "verify", label: "Doğrulama", sub: "4 katman", col: 3, row: 1 },
  { id: "debate", label: "Tartışma", sub: "hakemlik", col: 4, row: 1 },
  { id: "finalize", label: "Sonuç", sub: "güven + disclaimer", col: 5, row: 1 },
];

export const EDGES = [
  { from: "triaj", to: "mevzuat" },
  { from: "triaj", to: "emsal" },
  { from: "mevzuat", to: "draft" },
  { from: "emsal", to: "draft" },
  { from: "draft", to: "verify" },
  { from: "verify", to: "debate" },
  { from: "debate", to: "finalize" },
];

// Topolojik rank — öncül(done)/aktif/ardıl(idle) belirleme. mevzuat∥emsal aynı rank.
const RANK = { triaj: 0, mevzuat: 1, emsal: 1, draft: 2, verify: 3, debate: 4, finalize: 5 };

// Backend curated active_node → graph düğüm(leri). "retrieval" = mevzuat + emsal (paralel).
// chat/clarifier = soft-path (graf gizli) ama race penceresinde all-idle yerine triaj göster.
const ACTIVE_TO_RANK = {
  triaj: 0, chat: 0, clarifier: 0, retrieval: 1, draft: 2, verify: 3, debate: 4, finalize: 5,
};

// active_node yoksa (eski backend / v1) faz-event'inden infer (geriye uyumlu fallback).
const PHASE_TO_RANK = { triage: 0, sources: 1, drafting: 2, verifying: 3, final: 5 };

// Backend confidence_label → verify rozeti ton sınıfı. ASCII-stabil eşleme (Türkçe karakter
// regex'i kırılgan: "Yüksek güven".replace(/[^a-z]/g) → "yksekgven" → CSS sınıfı eşleşmez).
const VERIFY_TONE = {
  "Yüksek güven": "high",
  "Orta güven": "medium",
  "Dikkatli olun": "low",
};

export function verifyTone(confidenceLabel) {
  return VERIFY_TONE[confidenceLabel] || "default";
}

const SOFT_INTENTS = new Set(["chat", "smalltalk", "redirect", "out_of_scope_sensitive"]);

/* deriveNodeStatus → { nodeId: "idle"|"active"|"done"|"skipped" }
   phase: useChat faz ("triage".."final"), activeNode: backend curated etiket,
   intent: response_intent (soft-path tespiti). */
export function deriveNodeStatus({ phase, activeNode, intent } = {}) {
  const status = {};
  for (const n of NODES) status[n.id] = "idle";

  // SOFT-PATH (selam/yönlendirme): yalnız triaj çalışır, kalanlar skipped (HATA değil)
  if (intent && SOFT_INTENTS.has(intent)) {
    for (const n of NODES) status[n.id] = "skipped";
    status.triaj = "done";
    return status;
  }

  // Aktif rank: active_node (primary) > faz-event (fallback)
  let activeRank = null;
  if (activeNode != null && activeNode in ACTIVE_TO_RANK) activeRank = ACTIVE_TO_RANK[activeNode];
  else if (phase && phase in PHASE_TO_RANK) activeRank = PHASE_TO_RANK[phase];

  if (activeRank === null) return status; // henüz sinyal yok → hepsi idle

  // final/finalize → tüm zincir done
  if (phase === "final" || activeNode === "finalize") {
    for (const n of NODES) status[n.id] = "done";
    return status;
  }

  for (const n of NODES) {
    if (RANK[n.id] < activeRank) status[n.id] = "done";
    else if (RANK[n.id] === activeRank) status[n.id] = "active";
    else status[n.id] = "idle";
  }
  // "verifying" fazında debate'i de aktif göster (ADALET farkı: doğrulama+tartışma)
  if ((phase === "verifying" || activeNode === "verify") && status.debate === "idle") {
    status.debate = "active";
  }
  return status;
}

/* buildFigcaption → ekran-okuyucu için TR cümle özeti (animasyonsuz eşdeğer, a11y). */
export function buildFigcaption(status) {
  if (!status) return "Ajan akış şeması hazır.";
  const active = NODES.filter((n) => status[n.id] === "active").map((n) => n.label);
  const allDone = NODES.every((n) => status[n.id] === "done");
  if (allDone) return "Tüm ajanlar tamamlandı; cevap doğrulandı ve hazır.";
  if (status.triaj === "done" && active.length === 0) {
    return "Triaj tamamlandı; konu sınıflandırıldı.";
  }
  if (active.length === 0) return "Ajan akışı başlıyor.";
  if (active.length > 1) return active.join(" ve ") + " ajanları paralel çalışıyor.";
  return active[0] + " ajanı çalışıyor.";
}
