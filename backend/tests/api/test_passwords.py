"""Şifre hash/doğrulama (pbkdf2) testleri."""

from __future__ import annotations

import pytest

from api.passwords import hash_password, password_policy_issues, verify_password


@pytest.fixture(autouse=True)
def _fast_pbkdf2(monkeypatch):
    monkeypatch.setenv("PBKDF2_ITERATIONS", "1000")  # test hızı


def test_hash_verify_roundtrip():
    h = hash_password("Gizli123!")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("Gizli123!", h) is True
    assert verify_password("yanlis", h) is False


def test_hash_is_salted_unique():
    """Aynı şifre → farklı hash (per-kullanıcı salt)."""
    assert hash_password("aynisifre") != hash_password("aynisifre")


def test_verify_rejects_garbage():
    assert verify_password("x", "") is False
    assert verify_password("x", "bozuk-kayit") is False
    assert verify_password("x", "md5$1$aa$bb") is False  # alg uyumsuz


def test_raw_password_not_in_hash():
    h = hash_password("CokGizliParola")
    assert "CokGizliParola" not in h


def test_password_policy_accepts_strong_password():
    assert password_policy_issues("Gizli123!", email="ayse@example.com", name="Ayse") == []


def test_password_policy_rejects_common_compromised_password():
    issues = password_policy_issues("Password123")
    assert any("yaygın" in issue for issue in issues)


def test_password_policy_rejects_personal_information():
    issues = password_policy_issues("Ayse2026!", email="ayse@example.com", name="Ayse")
    assert any("e-posta" in issue for issue in issues)
