"""Paylaşımlı FastAPI dependency'leri.

require_user: kayıtlı (anonim-olmayan) kullanıcı zorunlu + KVKK-uyumlu saklama
anahtarı (fingerprint(sub,32)) döndürür. Tercih ve sohbet-geçmişi gibi
kullanıcı-bağlı kalıcı uçlar bunu kullanır (anonim → tercihleri/geçmişi yalnız
tarayıcıda tutulur).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from api.middleware.auth import Principal, authenticate
from api.pii import fingerprint

# Saklama anahtarı uzunluğu: 32 hex = 128 bit → PK/JSON-key çarpışma yüzeyini
# daralt (default 16=64-bit kullanıcı tabanı büyüyünce IDOR'a yol açabilir).
_KEY_LEN = 32


def owner_key(principal: Principal) -> str:
    """principal → KVKK-uyumlu saklama anahtarı (ham email değil)."""
    return fingerprint(principal.sub, _KEY_LEN)


def require_user(principal: Principal = Depends(authenticate)) -> str:
    """Kayıtlı kullanıcı zorunlu; saklama anahtarını döndürür.

    Anonim (AUTH_ENABLED=0 veya token yok) → 401. Çağıran uç, kullanıcının
    geçmişini/tercihini bu anahtarla saklar/okur.
    """
    if principal.anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="anonim oturum — bu veri yalnız bu cihazda saklanır",
        )
    return owner_key(principal)
