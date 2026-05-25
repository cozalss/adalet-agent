"""W8.5 — Log redaction processor testleri."""

from __future__ import annotations

from core.logging import _redact_dict, _redact_sensitive


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
