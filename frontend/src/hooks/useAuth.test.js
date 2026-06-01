/* useAuth saf yardımcıları — JWT decode + token→kullanıcı (süre/sub) testleri. */
import { describe, it, expect, beforeEach } from "vitest";
import { decodeJwt, userFromToken } from "./useAuth.js";

/** App'in decode'uyla uyumlu UTF-8 base64url (Türkçe char round-trip). */
function b64url(obj) {
  const bytes = new TextEncoder().encode(JSON.stringify(obj));
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function makeToken(payload) {
  return `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url(payload)}.sig`;
}
const future = () => Math.floor(Date.now() / 1000) + 3600;
const past = () => Math.floor(Date.now() / 1000) - 10;

describe("decodeJwt", () => {
  it("geçerli payload'ı UTF-8 ile çözer (Türkçe karakter)", () => {
    const c = decodeJwt(makeToken({ sub: "user:a@b.com", name: "Ayşe Şahin" }));
    expect(c.name).toBe("Ayşe Şahin");
    expect(c.sub).toBe("user:a@b.com");
  });
  it("bozuk token'da null döner", () => {
    expect(decodeJwt("not-a-jwt")).toBeNull();
    expect(decodeJwt("")).toBeNull();
  });
});

describe("userFromToken", () => {
  beforeEach(() => localStorage.clear());

  it("null/boş token → null", () => {
    expect(userFromToken(null)).toBeNull();
    expect(userFromToken("")).toBeNull();
  });

  it("geçerli token → kullanıcı nesnesi", () => {
    const u = userFromToken(makeToken({ sub: "user:a@b.com", role: "user", name: "Ali", email: "a@b.com", exp: future() }));
    expect(u).toEqual({ sub: "user:a@b.com", role: "user", name: "Ali", email: "a@b.com" });
  });

  it("email claim yoksa sub'tan türetir (user:/beta: önekini atar)", () => {
    expect(userFromToken(makeToken({ sub: "user:x@y.com", exp: future() })).email).toBe("x@y.com");
    expect(userFromToken(makeToken({ sub: "beta:z@w.com", exp: future() })).email).toBe("z@w.com");
  });

  it("sub yoksa → null", () => {
    expect(userFromToken(makeToken({ role: "user", exp: future() }))).toBeNull();
  });

  it("süresi dolmuş token → null + localStorage token temizlenir", () => {
    localStorage.setItem("adalet-token", "dummy");
    expect(userFromToken(makeToken({ sub: "user:a@b.com", exp: past() }))).toBeNull();
    expect(localStorage.getItem("adalet-token")).toBeNull();
  });
});
