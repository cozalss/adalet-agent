"""Kullanıcı tercihleri endpoint'i — /me/preferences (GET / PUT / DELETE).

UI tercihleri (görünen ad, yazı boyutu, hareket, yüksek kontrast, tercih edilen
hukuk alanları) auth'lu kullanıcı için cihazlar-arası senkronlanır. Tarayıcı
localStorage birincil kaynaktır; bu endpoint yalnız oturum açan kullanıcıya
çapraz-cihaz kalıcılık sağlar.

KVKK kırmızı çizgi:
- Yalnız hassas-OLMAYAN UI tercihleri. Soru / cevap / dilekçe BURADA saklanmaz.
- Saklama anahtarı = fingerprint(principal.sub) (ham email değil).
- Anonim kullanıcı → 401. Tercihler tarayıcıda kalır (sunucusuz).
- DELETE = KVKK silme hakkı (çapraz-cihaz sunucu kaydını temizler).
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field, field_validator

from api.dependencies import require_user
from api.limiter import limiter
from db.repositories.preferences import get_preference_repo

log = structlog.get_logger()
router = APIRouter(prefix="/me", tags=["me"])

# Production read-only container'da yazılabilir path → PREFS_STORE_FILE env (named
# volume). Dev'de default `data/preferences.json` (repo-relative). DB açıksa
# (DATABASE_URL) repo Postgres'e gider, bu dosya yolu kullanılmaz.
PREFS_STORE_PATH = Path(os.getenv("PREFS_STORE_FILE", "data/preferences.json"))

# 8 sivil hukuk alanı (api/schemas.Domain ∖ "unknown") — tercih için izinli set.
_ALLOWED_DOMAINS = {
    "tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari",
}
_TEXT_SCALES = {"compact", "normal", "large"}


class Preferences(BaseModel):
    """Hassas-olmayan UI tercihleri (sınır kontrollü).

    Not (KVKK): display_name kullanıcının KENDİ seçtiği görünen addır; yalnız
    kendi selamlamasında kullanılır, asla loglanmaz (put log'u yalnız text_scale +
    n_domains yazar) ve üçüncü tarafla paylaşılmaz. Eleman sayısı sınırı
    field_validator'da (≤8 izinli alan) — Field(max_length) kullanılmaz çünkü
    yinelenen/geçersiz girdiler 422 yerine sessizce filtrelenmeli.
    """

    display_name: str = Field(default="", max_length=60)
    text_scale: str = Field(default="normal")
    reduce_motion: bool = False
    high_contrast: bool = False
    preferred_domains: list[str] = Field(default_factory=list)

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        # Kontrol karakterlerini at; sadece görünür ad (selamlamada gösterilir).
        return "".join(ch for ch in v if ch.isprintable()).strip()

    @field_validator("text_scale")
    @classmethod
    def _valid_scale(cls, v: str) -> str:
        return v if v in _TEXT_SCALES else "normal"

    @field_validator("preferred_domains")
    @classmethod
    def _valid_domains(cls, v: list[str]) -> list[str]:
        # Yalnız bilinen sivil alanlar; sırayı koru, tekrarı at.
        seen: list[str] = []
        for d in v:
            if d in _ALLOWED_DOMAINS and d not in seen:
                seen.append(d)
        return seen


@router.get("/preferences", response_model=Preferences)
@limiter.limit("60/minute")
async def get_preferences(
    request: Request,
    sub_hash: str = Depends(require_user),
) -> Preferences:
    """Auth'lu kullanıcının kayıtlı tercihleri (yoksa varsayılan)."""
    repo = get_preference_repo(PREFS_STORE_PATH)
    stored = await repo.get(sub_hash)
    if not stored:
        return Preferences()
    # Bilinmeyen/eski alanları kırpmak için şemadan geçir (forward-compat).
    return Preferences(
        display_name=stored.get("display_name", ""),
        text_scale=stored.get("text_scale", "normal"),
        reduce_motion=bool(stored.get("reduce_motion", False)),
        high_contrast=bool(stored.get("high_contrast", False)),
        preferred_domains=stored.get("preferred_domains", []),
    )


@router.put("/preferences", response_model=Preferences)
@limiter.limit("30/minute")
async def put_preferences(
    request: Request,
    prefs: Preferences,
    sub_hash: str = Depends(require_user),
) -> Preferences:
    """Tercihleri kaydet (upsert). Şema doğrulama field_validator'larda."""
    repo = get_preference_repo(PREFS_STORE_PATH)
    await repo.upsert(sub_hash, prefs.model_dump())
    log.info(
        "preferences_updated",
        sub_hash=sub_hash[:12],
        text_scale=prefs.text_scale,
        n_domains=len(prefs.preferred_domains),
    )
    return prefs


@router.delete("/preferences", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_preferences(
    request: Request,
    sub_hash: str = Depends(require_user),
) -> None:
    """KVKK silme hakkı — çapraz-cihaz sunucu kaydını temizler."""
    repo = get_preference_repo(PREFS_STORE_PATH)
    await repo.delete(sub_hash)
    log.info("preferences_deleted", sub_hash=sub_hash[:12])
