"""Şifre hash/doğrulama — stdlib PBKDF2-HMAC-SHA256 (ek bağımlılık YOK).

ADALET lokal/minimal-deps ilkesi: bcrypt/passlib yerine stdlib. Format:
`pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>`. Per-kullanıcı salt + sabit-zaman
karşılaştırma. Ham şifre asla saklanmaz/loglanmaz.

Iterasyon sayısı OWASP 2023 önerisi (600k); testte PBKDF2_ITERATIONS env ile
düşürülebilir (hız).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata

_ALG = "pbkdf2_sha256"
_SALT_BYTES = 16
_MIN_PASSWORD_LEN = 8
_COMMON_COMPROMISED_PASSWORDS = {
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
}


def _iterations() -> int:
    # Dinamik okunur (test monkeypatch / env ile ayarlanabilir).
    return int(os.getenv("PBKDF2_ITERATIONS", "600000"))


def hash_password(password: str) -> str:
    """Ham şifre → `pbkdf2_sha256$iter$salt$hash` (saklamaya hazır)."""
    iters = _iterations()
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return f"{_ALG}${iters}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Sabit-zaman doğrulama. Geçersiz/bozuk kayıt → False (exception sızdırmaz)."""
    try:
        alg, iter_s, salt_hex, hash_hex = stored.split("$")
        if alg != _ALG:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iter_s)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def _normalize_password_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[^a-z0-9]", "", normalized)


def password_policy_issues(
    password: str,
    *,
    email: str = "",
    name: str = "",
) -> list[str]:
    """No-network signup password policy fallback."""
    issues: list[str] = []
    if len(password) < _MIN_PASSWORD_LEN:
        issues.append("Şifre en az 8 karakter olmalı.")
    if len(password) > 128:
        issues.append("Şifre en fazla 128 karakter olabilir.")

    categories = sum(
        [
            any(ch.islower() for ch in password),
            any(ch.isupper() for ch in password),
            any(ch.isdigit() for ch in password),
            any(not ch.isalnum() for ch in password),
        ]
    )
    if categories < 3:
        issues.append("Şifre büyük/küçük harf, rakam veya sembol türlerinden en az üçünü içermeli.")

    token = _normalize_password_token(password)
    if token in _COMMON_COMPROMISED_PASSWORDS:
        issues.append("Bu şifre çok yaygın veya sızıntı listelerinde görülen bir kalıp.")

    email_local = email.split("@", 1)[0] if email else ""
    for personal_value in (email_local, name):
        personal = _normalize_password_token(personal_value)
        if len(personal) >= 4 and personal in token:
            issues.append("Şifre e-posta veya ad bilgisi içermemeli.")
            break

    return issues
