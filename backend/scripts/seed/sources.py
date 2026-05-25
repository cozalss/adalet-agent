"""DecisionSource — mahkeme bazlı karar fetch abstraction.

Pipeline her mahkemeye aynı Protocol ile konuşur. Pagination, tool ismi ve
parametre şeması farklılıkları implementasyon detayı.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from retrieval.yargi_client import YargiClient, YargitayDecision

from .rate_limiter import AsyncTokenBucket

logger = logging.getLogger(__name__)


class EmptyDocumentError(Exception):
    """Belge fetch edildi ama metin boş — skip-on-error için ayrı tür."""


@dataclass(slots=True)
class DecisionRef:
    """Bir kararın listing-page kaydı — tam metin henüz çekilmemiş."""

    doc_id: str
    court: str
    chamber: str | None
    date: str | None
    title: str | None
    summary: str | None
    source_url: str
    raw: dict[str, Any] = field(default_factory=dict)


class DecisionSource(Protocol):
    """Tüm mahkeme kaynakları bu Protocol'u sağlar."""

    court_id: str

    def iter_refs(
        self,
        query: str,
        max_count: int,
        rate: AsyncTokenBucket,
        skip_ids: set[str],
    ) -> AsyncIterator[DecisionRef]:
        """Sayfalı arama — her DecisionRef'i yield eder.

        Concrete impls async generator olarak yazılır (`async def` + `yield`).
        Protocol stub yield içermez; tip kontrolü için AsyncIterator dönüş tipi.
        """
        ...

    async def fetch_text(
        self,
        ref: DecisionRef,
        rate: AsyncTokenBucket,
    ) -> str:
        """Bir kararın tam metnini Markdown olarak döndürür."""
        ...


def _to_ref(decision: YargitayDecision, doc_id_prefix: str) -> DecisionRef:
    return DecisionRef(
        doc_id=f"{doc_id_prefix}{decision.document_id}",
        court=decision.court_type,
        chamber=decision.chamber,
        date=decision.date,
        title=decision.title,
        summary=decision.summary,
        source_url=decision.source_url,
        raw=decision.raw,
    )


# Date pencereleri — keyword tükenmesini bypass etmek için her arama
# 4 farklı zaman aralığında yapılır → ~4x unique doc.
# yargi-mcp `kararTarihiStart` / `kararTarihiEnd` (ISO 8601) parametreleri.
_DATE_WINDOWS: tuple[tuple[str, str], ...] = (
    ("2024-01-01", "2026-12-31"),  # Son 2 yıl — en güncel
    ("2022-01-01", "2023-12-31"),  # 2 yıl önce
    ("2020-01-01", "2021-12-31"),  # 4-5 yıl önce
    ("2018-01-01", "2019-12-31"),  # En eski uzlaşmış içtihat
)


class _BedestenSource:
    """Yargıtay ve Danıştay için ortak Bedesten unified API implementasyonu."""

    def __init__(
        self,
        client: YargiClient,
        court_id: str,
        doc_id_prefix: str,
        search_method_name: str,
    ) -> None:
        self.client = client
        self.court_id = court_id
        self._prefix = doc_id_prefix
        self._search_method_name = search_method_name

    async def iter_refs(
        self,
        query: str,
        max_count: int,
        rate: AsyncTokenBucket,
        skip_ids: set[str],
    ) -> AsyncIterator[DecisionRef]:
        """Her keyword × her tarih penceresi → coverage artışı.

        Pencerelerden ardışık olarak ilerle: bir pencere tükenince diğerine geç.
        Aynı doc_id birden fazla pencerede dönerse `seen_in_run` ile filtrele.
        """
        yielded = 0
        seen_in_run: set[str] = set()
        search_fn = getattr(self.client, self._search_method_name)

        for date_start, date_end in _DATE_WINDOWS:
            if yielded >= max_count:
                return
            page = 1
            while yielded < max_count:
                await rate.acquire()
                try:
                    decisions = await search_fn(
                        query,
                        page_number=page,
                        date_start=date_start,
                        date_end=date_end,
                    )
                except Exception as exc:
                    logger.warning(
                        "source_search_failed",
                        extra={
                            "court": self.court_id,
                            "query": query,
                            "page": page,
                            "window": f"{date_start}..{date_end}",
                            "err": str(exc),
                        },
                    )
                    break  # Bu pencereyi atla, sonrakine geç

                if not decisions:
                    break

                new_count = 0
                for decision in decisions:
                    if yielded >= max_count:
                        return
                    ref = _to_ref(decision, self._prefix)
                    if ref.doc_id in seen_in_run or ref.doc_id in skip_ids:
                        continue
                    seen_in_run.add(ref.doc_id)
                    new_count += 1
                    yielded += 1
                    yield ref

                if new_count == 0:
                    # Bu sayfa hep duplicate → bu pencerede yenisi yok, sonraki pencereye geç
                    break
                page += 1

    async def fetch_text(self, ref: DecisionRef, rate: AsyncTokenBucket) -> str:
        await rate.acquire()
        raw_id = ref.doc_id.removeprefix(self._prefix)
        text = await self.client.get_document(raw_id)
        if not text:
            raise EmptyDocumentError(ref.doc_id)
        return text


class YargitaySource(_BedestenSource):
    def __init__(self, client: YargiClient) -> None:
        super().__init__(
            client=client,
            court_id="yargitay",
            doc_id_prefix="y-",
            search_method_name="search_yargitay",
        )


class DanistaySource(_BedestenSource):
    def __init__(self, client: YargiClient) -> None:
        super().__init__(
            client=client,
            court_id="danistay",
            doc_id_prefix="d-",
            search_method_name="search_danistay",
        )


class AnayasaSource:
    """Anayasa Mahkemesi — farklı tool ve şema, URL bazlı doc_id."""

    court_id = "anayasa"
    _prefix = "am-"

    def __init__(self, client: YargiClient) -> None:
        self.client = client

    async def iter_refs(
        self,
        query: str,
        max_count: int,
        rate: AsyncTokenBucket,
        skip_ids: set[str],
    ) -> AsyncIterator[DecisionRef]:
        yielded = 0
        page = 1
        seen_in_run: set[str] = set()

        while yielded < max_count:
            await rate.acquire()
            try:
                decisions = await self.client.search_anayasa(
                    keywords=[query],
                    decision_type="bireysel_basvuru",
                    page_to_fetch=page,
                )
            except Exception as exc:
                logger.warning(
                    "anayasa_search_failed",
                    extra={"query": query, "page": page, "err": str(exc)},
                )
                return

            if not decisions:
                return

            new_count = 0
            for decision in decisions:
                if yielded >= max_count:
                    return
                ref = _to_ref(decision, self._prefix)
                if ref.doc_id in seen_in_run or ref.doc_id in skip_ids:
                    continue
                seen_in_run.add(ref.doc_id)
                new_count += 1
                yielded += 1
                yield ref

            if new_count == 0:
                return
            page += 1

    async def fetch_text(self, ref: DecisionRef, rate: AsyncTokenBucket) -> str:
        await rate.acquire()
        document_url = ref.source_url or ref.doc_id.removeprefix(self._prefix)
        text = await self.client.get_anayasa_document(document_url)
        if not text:
            raise EmptyDocumentError(ref.doc_id)
        return text


def build_source(court_id: str, client: YargiClient) -> DecisionSource:
    """Court isminden DecisionSource instance üret."""
    if court_id == "yargitay":
        return YargitaySource(client)
    if court_id == "danistay":
        return DanistaySource(client)
    if court_id == "anayasa":
        return AnayasaSource(client)
    raise ValueError(f"Bilinmeyen court_id: {court_id}")
