"""Emsal (mahkeme kararı) endpoint'leri.

POST /emsal/full-text → bir kararın TAM metnini yargi-mcp'den ON-DEMAND çek.

Kök ihtiyaç: korpus kararları PARÇALI indeksliyor (karar başına ort. 1.2 dağınık chunk;
tam metin YOK). "İlgili Kararlar" paneli yalnız excerpt gösterebiliyordu (kullanıcı:
"hiçbiri tam değil"). Bu uç nokta, kullanıcı "tam metni getir" deyince kararın TAMAMINI
resmi kaynaktan (Bedesten/UYAP/Anayasa) canlı getirir.

Güvenlik:
    - Auth: Depends(authenticate) (ask ile aynı; AUTH_ENABLED=0 dev'de atlanır)
    - Rate limit: dış yargi-mcp'yi koru + abuse engelle (sabit kova)
    - SSRF: source_url doğrudan fetch EDİLMEZ — full_decision._route_fetch yalnız
      çıkarılan rakam-id'yi (Bedesten) ya da bilinen resmi domain'leri kullanır.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from api.limiter import limiter
from api.middleware.auth import Principal, authenticate
from api.schemas import FullDecisionRequest, FullDecisionResponse
from retrieval.full_decision import fetch_full_decision

router = APIRouter(prefix="/emsal", tags=["emsal"])


@router.post("/full-text", response_model=FullDecisionResponse)
@limiter.limit("20/minute")
async def emsal_full_text(
    request: Request,
    req: FullDecisionRequest,
    principal: Principal = Depends(authenticate),
) -> FullDecisionResponse:
    """Kararın tam metnini getir. Metin resmi kaynaktan gelir (sıfır halüsinasyon);
    getirilemezse text boş + error dolu (frontend dürüstçe 'getirilemedi' der)."""
    result = await fetch_full_decision(req.source_url, req.source_id, req.court)
    return FullDecisionResponse(**result)


__all__ = ("router",)
