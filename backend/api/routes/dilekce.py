"""Dilekçe PDF indirme + silme endpoint'leri.

Endpoint'ler:
    GET    /api/dilekce/{conversation_id}  → PDF stream (auth + ownership)
    DELETE /api/dilekce/{conversation_id}  → KVKK silme hakkı (auth + ownership)

Güvenlik:
    - **Auth zorunlu**: `Depends(authenticate)` (IDOR koruması)
    - **Ownership**: `principal.sub == entry.owner_sub` (kullanıcı sadece kendi
      PDF'ini indirir/siler). AUTH_ENABLED=0 dev ortamında atlanır.
    - UUID4 regex (path traversal koruması)
    - Content-Disposition: ASCII-only filename (renderer garantisi)
    - Template_id response'a SIZDIRILMAZ (path enumeration koruması)
    - Rate limit: `dilekce-download` bucket (limiter ile)
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from api.dilekce_store import delete_pdf, get_pdf
from api.limiter import limiter
from api.middleware.auth import Principal, authenticate

router = APIRouter(prefix="/api/dilekce", tags=["dilekce"])

# UUID4 strict — backend conversation_id zaten UUID4 üretiyor (api/routes/ask.py
# _new_conversation_id). Path traversal / SSRF / enumeration koruması.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
)


def _check_ownership(entry_owner_sub: str, principal_sub: str) -> None:
    """Sahiplik kontrolü — AUTH_ENABLED=0 dev ortamında atlanır.

    `entry.owner_sub == ""` durumu legacy (auth devre dışıyken üretilmiş
    eski kayıt) için tolere edilir; production'da bu durum oluşmamalı.
    """
    # Fail-secure default "1" (auth.py ile tutarlı — güvenlik C1). Lokal dev EXPLICIT "0".
    if os.getenv("AUTH_ENABLED", "1") not in {"1", "true", "yes"}:
        return
    if not entry_owner_sub:
        return  # legacy entry — auth devre dışıyken üretilmiş, sahiplik yok
    if entry_owner_sub != principal_sub:
        raise HTTPException(
            status_code=403, detail="Bu dilekçeye erişim yetkiniz yok.",
        )


@router.get(
    "/{conversation_id}",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}},
        400: {"description": "Geçersiz conversation_id formatı"},
        403: {"description": "Erişim yetkisi yok (başka kullanıcının PDF'i)"},
        404: {"description": "Dilekçe bulunamadı veya süresi doldu"},
    },
)
@limiter.limit("30/minute")
def download_dilekce(
    request: Request,
    conversation_id: str,
    principal: Principal = Depends(authenticate),
) -> Response:
    """Cache'deki PDF'i stream et. Auth + ownership zorunlu."""
    if not _UUID_RE.match(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    entry = get_pdf(conversation_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Dilekçe bulunamadı veya süresi doldu (15 dk).",
        )
    _check_ownership(entry.owner_sub, principal.sub)
    return Response(
        content=entry.pdf_bytes,
        media_type="application/pdf",
        headers={
            # ASCII-only filename — renderer _safe_filename garantisi (HTTP header).
            "Content-Disposition": f'attachment; filename="{entry.filename}"',
            "Cache-Control": "private, no-cache",
            # Template_id (örn "isHukuku/kidem...") iç dizin yapısını sızdırırdı;
            # security-reviewer önerisiyle response'a EKLENMEZ. Audit gerektirirse
            # server-side log'da yer alır.
        },
    )


_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get(
    "/{conversation_id}/docx",
    response_class=Response,
    responses={
        200: {"content": {_DOCX_MEDIA: {}}},
        400: {"description": "Geçersiz conversation_id formatı"},
        403: {"description": "Erişim yetkisi yok (başka kullanıcının dilekçesi)"},
        404: {"description": "Dilekçe/DOCX bulunamadı veya süresi doldu"},
    },
)
@limiter.limit("30/minute")
def download_dilekce_docx(
    request: Request,
    conversation_id: str,
    principal: Principal = Depends(authenticate),
) -> Response:
    """Editlenebilir DOCX'i stream et — vatandaş/avukat düzenler. Auth + ownership.

    Aynı conversation_id'de PDF ile yan yana saklanır. DOCX üretilmemişse 404.
    """
    if not _UUID_RE.match(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    entry = get_pdf(conversation_id)
    if entry is None or not entry.docx_bytes:
        raise HTTPException(
            status_code=404,
            detail="Dilekçe DOCX'i bulunamadı veya süresi doldu (15 dk).",
        )
    _check_ownership(entry.owner_sub, principal.sub)
    fname = entry.docx_filename or "dilekce.docx"
    return Response(
        content=entry.docx_bytes,
        media_type=_DOCX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "private, no-cache",
        },
    )


@router.delete(
    "/{conversation_id}",
    status_code=204,
    responses={
        204: {"description": "Dilekçe silindi"},
        400: {"description": "Geçersiz conversation_id formatı"},
        403: {"description": "Erişim yetkisi yok"},
        404: {"description": "Dilekçe bulunamadı"},
    },
)
@limiter.limit("30/minute")
def delete_dilekce(
    request: Request,
    conversation_id: str,
    principal: Principal = Depends(authenticate),
) -> Response:
    """KVKK m.7 — veri sahibi silme hakkı.

    Cache'den girdi varsa siler. Sahiplik kontrolü zorunlu (başka kullanıcının
    PDF'ini silinmeye karşı korur).
    """
    if not _UUID_RE.match(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    entry = get_pdf(conversation_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dilekçe bulunamadı.")
    _check_ownership(entry.owner_sub, principal.sub)
    delete_pdf(conversation_id)
    return Response(status_code=204)


__all__ = ("router",)
