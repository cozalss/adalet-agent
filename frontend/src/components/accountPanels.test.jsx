/* accountPanels — hesap menüsü panellerinin render testleri (ADALET kimliği). */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  HowItWorksPanel, ScopePanel, SourcesPanel,
  PrefsPanel, DisclaimerPanel, OpenSourcePanel, ProfilePanel,
} from "./accountPanels.jsx";

const html = (n) => renderToStaticMarkup(n);

it("HowItWorksPanel — 7 ajan + sıfır-uydurma taahhüdü", () => {
  const out = html(<HowItWorksPanel />);
  expect(out).toContain("Triaj Ajanı");
  expect(out).toContain("Doğrulama Ajanı");
  expect(out).toContain("Sıfır uydurma");
});

it("ScopePanel — 8 sivil alan + kapsam-dışı (ceza/aile dürüstlüğü)", () => {
  const out = html(<ScopePanel onAsk={() => {}} />);
  expect(out).toContain("Tüketici");
  expect(out).toContain("Kira");
  expect(out).toContain("Bilerek kapsam dışı");
  expect(out).toContain("Ceza hukuku");
});

it("SourcesPanel — resmî kaynaklar (mevzuat/Yargıtay/AYM) + doğrulama reddi", () => {
  const out = html(<SourcesPanel />);
  expect(out).toContain("mevzuat.gov.tr");
  expect(out).toContain("Yargıtay");
  expect(out).toContain("anayasa.gov.tr");
  expect(out).toContain("reddeder");
});

it("PrefsPanel — yazı boyutu + hareketi azalt + alan çipleri", () => {
  const prefs = { textScale: "normal", reduceMotion: false, highContrast: false, preferredDomains: ["kira"] };
  const out = html(<PrefsPanel prefs={prefs} setPref={() => {}} toggleDomain={() => {}} />);
  expect(out).toContain("Yazı boyutu");
  expect(out).toContain("Hareketi azalt");
  expect(out).toContain("Yüksek kontrast");
  expect(out).toContain("Tercih edilen alanlar");
});

it("DisclaimerPanel — hukuki danışmanlık değildir + yapar/yapamaz + yasal dayanak", () => {
  const out = html(<DisclaimerPanel />);
  expect(out).toContain("danışmanlık değildir");
  expect(out).toContain("Yapabildiklerim");
  expect(out).toContain("Yapamadıklarım");
  expect(out).toContain("temsil edemez");
  expect(out).toContain("Avukatlık Kanunu");
});

it("OpenSourcePanel — açık kaynak (MIT) + lisans özgürlükleri + neden önemli", () => {
  const out = html(<OpenSourcePanel />);
  expect(out).toContain("MIT");
  expect(out).toContain("İncele");
  expect(out).toContain("Çalıştır");
  expect(out).toContain("Değiştir");
  expect(out).toContain("Paylaş");
  expect(out).toContain("Neden önemli");
});

it("ProfilePanel — görünen ad alanı + kaydet", () => {
  const out = html(<ProfilePanel displayName="Ayşe" onSave={() => {}} onClose={() => {}} />);
  expect(out).toContain("Görünen ad");
  expect(out).toContain("Kaydet");
  expect(out).toContain("Ayşe");
});
