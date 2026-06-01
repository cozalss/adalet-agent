/* historyPanels — Sohbetlerde ara / Kaynaklar / Dosyalarım panel render testleri. */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SearchPanel, LibraryPanel, FilesPanel } from "./historyPanels.jsx";

const html = (n) => renderToStaticMarkup(n);
const now = () => new Date().toISOString();

describe("SearchPanel", () => {
  it("arama kutusu + sonuç satırı render eder", () => {
    const search = () => [{ id: "c1", title: "Kira sorunu", domain: "kira", updatedAt: now() }];
    const out = html(<SearchPanel search={search} onSelect={() => {}} />);
    expect(out).toContain("Geçmiş sohbetlerde ara");
    expect(out).toContain("Kira sorunu");
  });
  it("sonuç yoksa boş not", () => {
    expect(html(<SearchPanel search={() => []} onSelect={() => {}} />)).toContain("Henüz sohbet yok");
  });
});

describe("LibraryPanel", () => {
  it("boş → açıklama notu", () => {
    expect(html(<LibraryPanel sources={[]} />)).toContain("atıf yapılan");
  });
  it("kaynaklar → law/case etiketli satırlar", () => {
    const out = html(<LibraryPanel sources={[
      { title: "TBK m.344", doc_type: "law", convId: "c1", convTitle: "Kira" },
      { title: "Yargıtay 9.HD", doc_type: "case", convId: "c2", convTitle: "İş" },
    ]} onSelect={() => {}} />);
    expect(out).toContain("TBK m.344");
    expect(out).toContain("Kanun");
    expect(out).toContain("Yargıtay");
  });
});

describe("FilesPanel", () => {
  it("boş → açıklama notu (metin saklanmaz)", () => {
    expect(html(<FilesPanel files={[]} />)).toContain("metin değil");
  });
  it("dosyalar → ad + karakter + PII bayrağı", () => {
    const out = html(<FilesPanel files={[
      { filename: "kira.pdf", n_chars: 1200, pii: true, convId: "c1", convTitle: "Kira" },
    ]} onSelect={() => {}} />);
    expect(out).toContain("kira.pdf");
    expect(out).toContain("kişisel veri");
  });
});
