import { afterEach, describe, expect, it, vi } from "vitest";

import {
  normalizePasswordToken,
  passwordPolicyIssues,
  passwordPolicyIssuesWithBreachCheck,
  pwnedPasswordCount,
  sha1Hex,
} from "./passwordPolicy.js";

const originalFetch = global.fetch;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  global.fetch = originalFetch;
});

describe("passwordPolicy", () => {
  it("normalizes punctuation and casing for denylist checks", () => {
    expect(normalizePasswordToken(" Password-123 ")).toBe("password123");
  });

  it("accepts a strong non-personal password", () => {
    expect(passwordPolicyIssues("Gizli123!", { email: "ayse@example.com", name: "Ayse" })).toEqual([]);
  });

  it("rejects common compromised password patterns", () => {
    expect(passwordPolicyIssues("Password123")).toContain(
      "Bu şifre çok yaygın veya sızıntı listelerinde görülen bir kalıp.",
    );
  });

  it("rejects email/name reuse", () => {
    expect(passwordPolicyIssues("Ayse2026!", { email: "ayse@example.com", name: "Ayse" })).toContain(
      "Şifre e-posta veya ad bilgisi içermemeli.",
    );
  });

  it("skips HIBP range lookup unless production env enables it", async () => {
    global.fetch = vi.fn();
    await expect(passwordPolicyIssuesWithBreachCheck("Gizli123!")).resolves.toEqual([]);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("detects pwned passwords via HIBP k-anonymity range response", async () => {
    vi.stubEnv("VITE_HIBP_PASSWORD_CHECK", "1");
    const hash = await sha1Hex("Unique123!");
    const suffix = hash.slice(5);
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => `00000000000000000000000000000000000:0\r\n${suffix}:7\r\n`,
    });
    global.fetch = fetchImpl;

    await expect(pwnedPasswordCount("Unique123!", { fetchImpl })).resolves.toBe(7);
    await expect(passwordPolicyIssuesWithBreachCheck("Unique123!")).resolves.toContain(
      "Bu şifre sızıntı verilerinde 7 kez görüldü; lütfen farklı bir şifre seçin.",
    );
  });

  it("fails closed when the HIBP range lookup is unavailable", async () => {
    vi.stubEnv("VITE_HIBP_PASSWORD_CHECK", "1");
    global.fetch = vi.fn().mockResolvedValue({ ok: false, text: async () => "" });
    await expect(passwordPolicyIssuesWithBreachCheck("Unique123!")).resolves.toContain(
      "Şifre sızıntı kontrolü şu an yapılamadı. Lütfen biraz sonra tekrar deneyin.",
    );
  });
});
