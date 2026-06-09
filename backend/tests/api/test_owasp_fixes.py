"""OWASP A01 denetim fix'lerinin regresyon testleri.

Kapsanan üç fix:
  1. dilekce.py _check_ownership: boş owner_sub fail-closed (403, IDOR bypass kapalı)
  2. ask.py _bind_or_verify_owner: set_owner_if_absent fail-closed (503, suppress kaldırıldı)
  3. ask.py _detect_minor: CLAUDE.md <18 yaş filtresi
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.routes.ask import _detect_minor
from api.routes.dilekce import _check_ownership

# ---------------------------------------------------------------------------
# Fix 1 — dilekce._check_ownership: boş owner_sub fail-closed
# ---------------------------------------------------------------------------


def test_empty_owner_sub_raises_403(monkeypatch):
    """Boş owner_sub artık 403 yükseltmeli (fail-closed)."""
    monkeypatch.setenv("AUTH_ENABLED", "1")
    with pytest.raises(HTTPException) as exc_info:
        _check_ownership("", "any-principal")
    assert exc_info.value.status_code == 403


def test_mismatched_owner_raises_403(monkeypatch):
    """Farklı owner_sub hâlâ 403 yükseltmeli."""
    monkeypatch.setenv("AUTH_ENABLED", "1")
    with pytest.raises(HTTPException) as exc_info:
        _check_ownership("alice", "bob")
    assert exc_info.value.status_code == 403


def test_matching_owner_passes(monkeypatch):
    """owner_sub == principal_sub → istisna yok."""
    monkeypatch.setenv("AUTH_ENABLED", "1")
    _check_ownership("alice", "alice")  # raise etmemeli


def test_auth_disabled_skips_ownership(monkeypatch):
    """AUTH_ENABLED=0 → ownership atlanır (dev ortamı)."""
    monkeypatch.setenv("AUTH_ENABLED", "0")
    _check_ownership("", "anyone")   # raise etmemeli
    _check_ownership("alice", "bob")  # raise etmemeli


# ---------------------------------------------------------------------------
# Fix 2 — ask._bind_or_verify_owner: set_owner_if_absent fail-closed (503)
# Bu iç async fonksiyon; store mock'u ile entegrasyon testi.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_owner_fail_closed_on_store_error(monkeypatch):
    """store.set_owner_if_absent exception atarsa → HTTPException 503 (suppress DEĞİL)."""
    from fastapi import HTTPException

    import api.routes.ask as ask_mod
    from api.middleware.auth import Principal

    class _FakeStore:
        async def get_owner(self, conv_id: str):
            return None  # mevcut yok → bind yoluna gir

        async def set_owner_if_absent(self, conv_id: str, owner: str):
            raise ConnectionError("redis down")

    monkeypatch.setattr(ask_mod, "get_store", lambda: _FakeStore())

    principal = Principal(sub="user-1", kind="user", anonymous=False)
    with pytest.raises(HTTPException) as exc_info:
        await ask_mod._bind_or_verify_owner("test-conv", principal)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_bind_owner_idor_blocks_second_user(monkeypatch):
    """Farklı sahibin conv_id'sine erişim → 403."""
    from fastapi import HTTPException

    import api.routes.ask as ask_mod
    from api.middleware.auth import Principal
    from api.pii import fingerprint

    owner_fp = fingerprint("owner-user")

    class _FakeStore:
        async def get_owner(self, conv_id: str):
            return owner_fp  # mevcut sahip var

        async def set_owner_if_absent(self, conv_id: str, owner: str):
            pass

    monkeypatch.setattr(ask_mod, "get_store", lambda: _FakeStore())

    attacker = Principal(sub="attacker-user", kind="user", anonymous=False)
    with pytest.raises(HTTPException) as exc_info:
        await ask_mod._bind_or_verify_owner("test-conv", attacker)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_bind_owner_anonymous_is_noop(monkeypatch):
    """Anonim principal → ownership kontrolü yok (AUTH_ENABLED=0 dev modu)."""
    import api.routes.ask as ask_mod
    from api.middleware.auth import Principal

    called = []

    class _FakeStore:
        async def get_owner(self, conv_id: str):
            called.append("get_owner")
            return

        async def set_owner_if_absent(self, conv_id: str, owner: str):
            called.append("set_owner")

    monkeypatch.setattr(ask_mod, "get_store", lambda: _FakeStore())

    anon = Principal(sub="anon", kind="anonymous", anonymous=True)
    await ask_mod._bind_or_verify_owner("test-conv", anon)
    assert not called  # store'a hiç dokunmamalı


# ---------------------------------------------------------------------------
# Fix 3 — _detect_minor: CLAUDE.md <18 yaş filtresi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "15 yaşındayım kira sorunum var",
    "Ben 12 yaşındayım",
    "yaşım 9, annemle soruyorum",
    "17 yaşım var, iş hukuku sorusu",
    "16 yaşında bir çocuğum",
    "8 yaşındayım",
    "1 yaşındayım",          # köşe durum
    "17 yaşındayım tazminat",
])
def test_detect_minor_positive(text: str):
    """18 yaş altı beyan → True döner."""
    assert _detect_minor(text), f"Minor tespit edilmedi: {text!r}"


@pytest.mark.parametrize("text", [
    "18 yaşındayım kira sorunum var",
    "19 yaşındayım",
    "35 yaşında işçiyim",
    "42 yaşında işçiyim, 15 yıllık kıdemim var",  # 15 yıl kıdem, yaş değil
    "kira sözleşmesi 15. madde",              # 15 madde, yaş değil
    "2015 yılında imzalandı",
    "15 TL ödedim",
    "ihbar süresi 15 gün",
])
def test_detect_minor_negative(text: str):
    """18 yaş altı beyan YOK → False döner (yanlış pozitif yok)."""
    assert not _detect_minor(text), f"Yanlış pozitif: {text!r}"


def test_detect_minor_boundary_18():
    """18 yaş sınır değer → False (minor DEĞİL)."""
    assert not _detect_minor("18 yaşındayım")


def test_detect_minor_boundary_17():
    """17 yaş sınır değer → True (minor)."""
    assert _detect_minor("17 yaşındayım")


def test_detect_minor_case_insensitive():
    """Büyük/küçük harf fark etmemeli."""
    assert _detect_minor("15 YAŞINDAYım")
    assert _detect_minor("YAŞIM 12")
