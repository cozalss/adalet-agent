/* AuthPage — giriş/kayıt sayfası render testi (varsayılan giriş modu). */
import React from "react";
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AuthPage } from "./AuthPage.jsx";

const html = (n) => renderToStaticMarkup(<AuthPage onLogin={() => {}} onRegister={() => {}} onGuest={() => {}} />);

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
  it("misafir devam et seçeneği + disclaimer", () => {
    expect(out).toContain("Misafir olarak devam et");
    expect(out).toContain("danışmanlık değildir");
  });
});
