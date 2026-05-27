"""W8.5 — Log redaction processor testleri."""

from __future__ import annotations

from core.logging import (
    _mask_pii_in_strings,
    _mask_pii_nested,
    _redact_dict,
    _redact_sensitive,
)


def test_redact_top_level_password():
    out = _redact_sensitive(None, "info", {"event": "login", "password": "supersecret"})
    assert out["password"] == "[REDACTED]"
    assert out["event"] == "login"


def test_redact_token_variants():
    payload = {
        "access_token": "tok-123",
        "refresh_token": "rtk-456",
        "jwt_secret": "abc",
        "api_key": "alpha",
        "session_id": "sess",  # NOT a token key → kalır
    }
    out = _redact_sensitive(None, "info", payload)
    assert out["access_token"] == "[REDACTED]"
    assert out["refresh_token"] == "[REDACTED]"
    assert out["jwt_secret"] == "[REDACTED]"
    assert out["api_key"] == "[REDACTED]"
    # session_id "_id" suffixli → "_key" pattern'ine uymuyor; kalmalı
    assert out["session_id"] == "sess"


def test_redact_nested_dict():
    payload = {
        "user": {
            "name": "Ayşe",
            "password": "secret",
            "token": "abc",
        },
        "info": "hello",
    }
    out = _redact_sensitive(None, "info", payload)
    assert out["user"]["password"] == "[REDACTED]"
    assert out["user"]["token"] == "[REDACTED]"
    assert out["user"]["name"] == "Ayşe"
    assert out["info"] == "hello"


def test_redact_case_insensitive():
    out = _redact_sensitive(None, "info", {"Authorization": "Bearer xyz"})
    assert out["Authorization"] == "[REDACTED]"


def test_redact_no_match_returns_clean():
    payload = {"event": "ok", "domain": "isHukuku", "n_claims": 3}
    out = _redact_sensitive(None, "info", dict(payload))
    assert out == payload


def test_redact_dict_helper():
    nested = {"a": 1, "secret": "x", "inner": {"password": "p", "ok": True}}
    out = _redact_dict(nested)
    assert out["a"] == 1
    assert out["secret"] == "[REDACTED]"
    assert out["inner"]["password"] == "[REDACTED]"
    assert out["inner"]["ok"] is True


# --------------------------------------------------------------------------
#  Recursion — liste içindeki hassas anahtar/PII (KVKK)
# --------------------------------------------------------------------------


def test_redact_recurses_into_lists():
    """Liste değerleri içindeki dict'lerin hassas anahtarları da redact edilmeli."""
    payload = {"items": [{"token": "abc"}, {"ok": 1}], "msg": "x"}
    out = _redact_sensitive(None, "info", payload)
    assert out["items"][0]["token"] == "[REDACTED]"
    assert out["items"][1]["ok"] == 1
    assert out["msg"] == "x"


def test_redact_recurses_into_nested_lists():
    """Liste-içinde-liste-içinde-dict bile redact edilmeli."""
    payload = {"a": [[{"password": "p"}]]}
    out = _redact_sensitive(None, "info", payload)
    assert out["a"][0][0]["password"] == "[REDACTED]"


def test_mask_pii_nested_recurses_list_and_dict():
    """_mask_pii_nested liste + dict içine inip string'lerde mask uygular."""
    from api.pii import MaskResult

    def fake_mask(text: str) -> MaskResult:
        if "SECRET" in text:
            return MaskResult(text.replace("SECRET", "[X]"), {"x": 1})
        return MaskResult(text, {})

    value = {"turns": ["bu SECRET bir değer", "kısa"], "n": 5}
    out = _mask_pii_nested(value, fake_mask)
    assert out["turns"][0] == "bu [X] bir değer"
    assert out["turns"][1] == "kısa"   # <8 char → dokunulmaz
    assert out["n"] == 5


def test_mask_pii_in_strings_masks_nested_list(monkeypatch):
    """Liste içindeki TCKN log processor'da maskelenmeli (eskiden atlanıyordu)."""
    import api.pii as pii_mod

    monkeypatch.setattr(pii_mod, "PII_ENABLED", True)
    payload = {"turns": ["TCKN 12345678901 ile başvurdum"]}
    out = _mask_pii_in_strings(None, "info", payload)
    assert "12345678901" not in str(out["turns"])
