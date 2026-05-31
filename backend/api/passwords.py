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

_ALG = "pbkdf2_sha256"
_SALT_BYTES = 16


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
