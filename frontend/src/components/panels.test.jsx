/* panels.jsx — PredictionCard / AgentTrace özet / EvidenceStats render testleri. */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PredictionCard, AgentTrace, EvidenceStats, QuickTyping } from "./panels.jsx";

const html = (n) => renderToStaticMarkup(n);

describe("QuickTyping", () => {
  it("role=status + 3 nokta + etiket", () => {
    const out = html(<QuickTyping label="Yazıyor" />);
    expect(out).toContain('role="status"');
    expect(out).toContain("Yazıyor");
    expect((out.match(/qt-dot"/g) || []).length).toBe(3); // 3 nokta (kapsayıcı qt-dots hariç)
  });
});

describe("PredictionCard", () => {
  it("null tahmin → hiçbir şey render etmez", () => {
    expect(html(<PredictionCard prediction={null} />)).toBe("");
  });

  it("kazandi → lehe eğilim + % + tone-ok + gerekçe + zorunlu disclaimer", () => {
    const out = html(<PredictionCard prediction={{
      verdictClass: "kazandi", confidence: 70, similarCaseIds: ["E.2021/1", "E.2020/2"],
      reasoning: "benzer kararlar lehe", disclaimer: "mahkeme garantisi değildir",
    }} />);
    expect(out).toContain("Lehe eğilim");
    expect(out).toContain("%70");
    expect(out).toContain("tone-ok");
    expect(out).toContain("benzer kararlar lehe");
    expect(out).toContain("mahkeme garantisi değildir");
    expect(out).toContain("E.2021/1");
  });

  it("belirsiz → yüzde/bar gösterilmez", () => {
    const out = html(<PredictionCard prediction={{ verdictClass: "belirsiz", confidence: 0, similarCaseIds: [], disclaimer: "d" }} />);
    expect(out).toContain("Belirsiz");
    expect(out).not.toContain("pred-bar");
    expect(out).not.toContain("pred-pct");
  });
});

describe("AgentTrace (özet)", () => {
  it("iddia + debate yoksa → hiçbir şey render etmez", () => {
    expect(html(<AgentTrace claims={[]} sourceCount={0} />)).toBe("");
  });

  it("iddia özetini hesaplar (X/Y doğrulandı)", () => {
    const out = html(<AgentTrace claims={[{ verified: true }, { verified: false }]} sourceCount={3} domain="kira" />);
    expect(out).toContain("1/2 iddia kaynakla doğrulandı");
  });
});

describe("EvidenceStats", () => {
  it("kaynak sayısı + doğrulanan iddia (X/Y) gösterir", () => {
    const out = html(<EvidenceStats confidence={88} sourceCount={5}
      claims={[{ verified: true }, { verified: true }, { verified: false }]} />);
    expect(out).toContain("Güven");
    expect(out).toContain("Kaynak");
    expect(out).toContain(">5<");           // sourceCount
    expect(out).toContain("Doğrulanan iddia");
    expect(out).toContain(">2<");           // verified
    expect(out).toContain("/3");            // total
  });

  it("iddia yoksa doğrulanan-iddia bloğu gösterilmez", () => {
    const out = html(<EvidenceStats confidence={50} sourceCount={2} claims={[]} />);
    expect(out).not.toContain("Doğrulanan iddia");
  });
});
