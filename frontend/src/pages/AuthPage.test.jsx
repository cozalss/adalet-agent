/* AuthPage — giriş/kayıt sayfası render testi (varsayılan giriş modu).
   Misafir modu KALDIRILDI: "Misafir olarak devam et" seçeneği OLMAMALI. */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AuthPage } from "./AuthPage.jsx";

const html = (props) => renderToStaticMarkup(
  <AuthPage onLogin={() => {}} onRegister={() => {}} {...props} />,
);

describe("AuthPage", () => {
  const out = html();

  it("marka paneli + tagline render eder", () => {
    expect(out).toContain("ADALET");
    expect(out).toContain("doğrulanmış");
  });
  it("Giriş/Kayıt sekmeleri (tablist)", () => {
    expect(out).toContain('role="tablist"');
    expect(out).toContain("Giriş");
    expect(out).toContain("Kayıt ol");
  });
  it("varsayılan giriş modu: e-posta + şifre + giriş yap", () => {
    expect(out).toContain("Tekrar hoş geldiniz");
    expect(out).toContain("E-posta");
    expect(out).toContain("Şifre");
    expect(out).toContain("Giriş yap");
  });
  it("disclaimer var; misafir seçeneği YOK (kayıt/giriş zorunlu)", () => {
    expect(out).toContain("danışmanlık değildir");
    expect(out).not.toContain("Misafir olarak devam et");
  });
  it("onGoogle verilince 'Google ile devam et' butonu çıkar", () => {
    expect(html({ onGoogle: () => {} })).toContain("Google ile devam et");
  });
});
