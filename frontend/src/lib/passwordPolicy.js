const COMMON_COMPROMISED_PASSWORDS = new Set([
  "12345678",
  "123456789",
  "11111111",
  "00000000",
  "password",
  "password1",
  "password123",
  "qwerty123",
  "qwertyui",
  "admin123",
  "letmein1",
  "iloveyou",
  "welcome1",
  "adalet123",
]);
const HIBP_RANGE_ENDPOINT = "https://api.pwnedpasswords.com/range/";

export function normalizePasswordToken(value = "") {
  return String(value).normalize("NFKC").toLowerCase().trim().replace(/[^a-z0-9]/g, "");
}

export function passwordPolicyIssues(password, { email = "", name = "" } = {}) {
  const issues = [];
  const value = String(password || "");
  if (value.length < 8) issues.push("Şifre en az 8 karakter olmalı.");
  if (value.length > 128) issues.push("Şifre en fazla 128 karakter olabilir.");

  const categories = [
    /[a-z]/.test(value),
    /[A-Z]/.test(value),
    /\d/.test(value),
    /[^A-Za-z0-9]/.test(value),
  ].filter(Boolean).length;
  if (categories < 3) {
    issues.push("Şifre büyük/küçük harf, rakam veya sembol türlerinden en az üçünü içermeli.");
  }

  const token = normalizePasswordToken(value);
  if (COMMON_COMPROMISED_PASSWORDS.has(token)) {
    issues.push("Bu şifre çok yaygın veya sızıntı listelerinde görülen bir kalıp.");
  }

  const emailLocal = String(email || "").split("@")[0] || "";
  for (const personalValue of [emailLocal, name]) {
    const personal = normalizePasswordToken(personalValue);
    if (personal.length >= 4 && token.includes(personal)) {
      issues.push("Şifre e-posta veya ad bilgisi içermemeli.");
      break;
    }
  }

  return issues;
}

export function assertPasswordPolicy(password, options = {}) {
  const issues = passwordPolicyIssues(password, options);
  if (issues.length) throw new Error(issues[0]);
}

export function hibpPasswordCheckEnabled() {
  return import.meta.env.VITE_HIBP_PASSWORD_CHECK === "1";
}

function bytesToHex(buffer) {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();
}

export async function sha1Hex(value, cryptoImpl = globalThis.crypto) {
  if (!cryptoImpl?.subtle) throw new Error("Tarayıcı parola sızıntı kontrolünü desteklemiyor.");
  const data = new TextEncoder().encode(String(value));
  const digest = await cryptoImpl.subtle.digest("SHA-1", data);
  return bytesToHex(digest);
}

export async function pwnedPasswordCount(
  password,
  {
    fetchImpl = globalThis.fetch,
    cryptoImpl = globalThis.crypto,
    endpoint = HIBP_RANGE_ENDPOINT,
  } = {},
) {
  if (typeof fetchImpl !== "function") throw new Error("Parola sızıntı kontrolü kullanılamıyor.");
  const hash = await sha1Hex(password, cryptoImpl);
  const prefix = hash.slice(0, 5);
  const suffix = hash.slice(5);
  const res = await fetchImpl(`${endpoint}${prefix}`, { headers: { "Add-Padding": "true" } });
  if (!res?.ok) throw new Error("Parola sızıntı kontrolü başarısız.");
  const body = await res.text();
  for (const line of body.split(/\r?\n/)) {
    const [candidate, count] = line.trim().split(":");
    if (candidate?.toUpperCase() === suffix) return Number.parseInt(count || "0", 10) || 0;
  }
  return 0;
}

export async function passwordPolicyIssuesWithBreachCheck(password, options = {}) {
  const issues = passwordPolicyIssues(password, options);
  if (issues.length || !hibpPasswordCheckEnabled()) return issues;
  let count = 0;
  try {
    count = await pwnedPasswordCount(password);
  } catch {
    return ["Şifre sızıntı kontrolü şu an yapılamadı. Lütfen biraz sonra tekrar deneyin."];
  }
  return count > 0
    ? [`Bu şifre sızıntı verilerinde ${count} kez görüldü; lütfen farklı bir şifre seçin.`]
    : [];
}

export async function assertPasswordPolicyWithBreachCheck(password, options = {}) {
  const issues = await passwordPolicyIssuesWithBreachCheck(password, options);
  if (issues.length) throw new Error(issues[0]);
}
