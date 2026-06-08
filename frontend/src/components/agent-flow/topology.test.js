import { describe, it, expect } from "vitest";
import { NODES, EDGES, deriveNodeStatus, buildFigcaption, verifyTone } from "./topology.js";

describe("topology", () => {
  it("7 çekirdek ajan + DAG kenarları", () => {
    expect(NODES.map((n) => n.id)).toEqual(
      ["triaj", "mevzuat", "emsal", "draft", "verify", "debate", "finalize"],
    );
    expect(EDGES.length).toBe(7);
  });
});

describe("deriveNodeStatus — active_node (primary)", () => {
  it("triaj → triaj active, kalan idle", () => {
    const s = deriveNodeStatus({ activeNode: "triaj" });
    expect(s.triaj).toBe("active");
    expect(s.draft).toBe("idle");
  });
  it("retrieval → mevzuat+emsal active (paralel), triaj done", () => {
    const s = deriveNodeStatus({ activeNode: "retrieval" });
    expect(s.triaj).toBe("done");
    expect(s.mevzuat).toBe("active");
    expect(s.emsal).toBe("active");
    expect(s.draft).toBe("idle");
  });
  it("draft → retrieval done, draft active", () => {
    const s = deriveNodeStatus({ activeNode: "draft" });
    expect(s.mevzuat).toBe("done");
    expect(s.emsal).toBe("done");
    expect(s.draft).toBe("active");
    expect(s.verify).toBe("idle");
  });
  it("verify → draft done, verify+debate active (ADALET farkı)", () => {
    const s = deriveNodeStatus({ activeNode: "verify" });
    expect(s.draft).toBe("done");
    expect(s.verify).toBe("active");
    expect(s.debate).toBe("active");
  });
  it("finalize → tüm zincir done", () => {
    const s = deriveNodeStatus({ activeNode: "finalize" });
    expect(NODES.every((n) => s[n.id] === "done")).toBe(true);
  });
});

describe("deriveNodeStatus — faz-event fallback (active_node yok, v1 backend)", () => {
  it("phase=triage → triaj active", () => {
    expect(deriveNodeStatus({ phase: "triage" }).triaj).toBe("active");
  });
  it("phase=sources → triaj done, mevzuat+emsal active", () => {
    const s = deriveNodeStatus({ phase: "sources" });
    expect(s.triaj).toBe("done");
    expect(s.mevzuat).toBe("active");
    expect(s.emsal).toBe("active");
  });
  it("phase=verifying → verify+debate active", () => {
    const s = deriveNodeStatus({ phase: "verifying" });
    expect(s.verify).toBe("active");
    expect(s.debate).toBe("active");
  });
  it("phase=final → hepsi done", () => {
    const s = deriveNodeStatus({ phase: "final" });
    expect(NODES.every((n) => s[n.id] === "done")).toBe(true);
  });
});

describe("deriveNodeStatus — soft-path & boş", () => {
  it("smalltalk → yalnız triaj done, kalan skipped (HATA değil)", () => {
    const s = deriveNodeStatus({ intent: "smalltalk", phase: "triage" });
    expect(s.triaj).toBe("done");
    expect(s.draft).toBe("skipped");
    expect(s.finalize).toBe("skipped");
    expect(Object.values(s)).not.toContain("error");
  });
  it("sinyal yok → hepsi idle", () => {
    const s = deriveNodeStatus({});
    expect(NODES.every((n) => s[n.id] === "idle")).toBe(true);
  });
});

describe("verifyTone — confidence_label → ASCII ton sınıfı", () => {
  it("gerçek backend etiketleri eşlenir (Türkçe karakterli)", () => {
    expect(verifyTone("Yüksek güven")).toBe("high");
    expect(verifyTone("Orta güven")).toBe("medium");
    expect(verifyTone("Dikkatli olun")).toBe("low");
  });
  it("bilinmeyen/boş → default (CSS temel ton)", () => {
    expect(verifyTone("")).toBe("default");
    expect(verifyTone(undefined)).toBe("default");
    expect(verifyTone("Saçma")).toBe("default");
  });
});

describe("buildFigcaption — a11y TR cümle", () => {
  it("paralel retrieval → 've' ile iki ajan", () => {
    const cap = buildFigcaption(deriveNodeStatus({ activeNode: "retrieval" }));
    expect(cap).toMatch(/Mevzuat ve Emsal/);
    expect(cap).toMatch(/paralel/);
  });
  it("final → tamamlandı + doğrulandı", () => {
    const cap = buildFigcaption(deriveNodeStatus({ phase: "final" }));
    expect(cap).toMatch(/tamamlandı/i);
  });
  it("tek aktif → '… ajanı çalışıyor'", () => {
    expect(buildFigcaption(deriveNodeStatus({ activeNode: "draft" }))).toMatch(/çalışıyor/);
  });
});
