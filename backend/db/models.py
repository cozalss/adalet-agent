"""SQLModel tablo tanımları — ilişkisel app verisi.

Dosya-tabanlı (feedback JSONL, api_keys JSON, audit log) yerine kalıcı,
sorgulanabilir DB. Tipler Postgres + SQLite (test) ortak alt-kümesinde:
JSON için `sa.JSON` (her ikisi destekler), zaman için ISO string/datetime.

KVKK: principal_sub asla HAM saklanmaz — yalnız fingerprint (sub_hash).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Feedback(SQLModel, table=True):
    """Kullanıcı feedback — eski feedback_*.jsonl yerine.

    comment PII-mask edilmiş; sub_hash fingerprint (ham email değil).
    """

    __tablename__ = "feedback"

    feedback_id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    principal_kind: str
    principal_sub_hash: str = Field(index=True)
    conversation_id: str = Field(index=True)
    turn_index: int | None = None
    rating: str  # "up" | "down"
    comment_masked: str = ""


class AuditEvent(SQLModel, table=True):
    """Audit olayı — eski log-dosyası yerine sorgulanabilir tablo."""

    __tablename__ = "audit_event"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    event: str = Field(index=True)
    principal_kind: str = ""
    principal_sub_hash: str = Field(default="", index=True)
    conversation_id: str = ""
    detail: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))


class ApiKey(SQLModel, table=True):
    """B2B API key — eski API_KEYS_FILE JSON yerine.

    `key_hash` = SHA-256(raw). Ham key asla saklanmaz. `active` ile revoke.
    """

    __tablename__ = "api_key"

    key_hash: str = Field(primary_key=True)
    label: str
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class Invite(SQLModel, table=True):
    """Beta davet kodu — kod tek kullanımlık, kabul edilince used=True."""

    __tablename__ = "invite"

    code: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    used: bool = Field(default=False, index=True)
    used_by_sub_hash: str | None = None
    used_at: datetime | None = None


class EvalRun(SQLModel, table=True):
    """Benchmark/eval koşusu — Üye 4 tez metrikleri (Ragas, judge, vs.).

    metrics JSON: {faithfulness, answer_relevancy, context_precision, ...}.
    """

    __tablename__ = "eval_run"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    run_name: str = Field(index=True)
    git_sha: str = ""
    n_cases: int = 0
    metrics: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))
    notes: str = ""


class UserPreference(SQLModel, table=True):
    """Kullanıcı UI tercihleri — auth'lu kullanıcı için cihazlar-arası senkron.

    KVKK kırmızı çizgi:
    - PK = sub_hash (fingerprint(principal.sub)), HAM email DEĞİL.
    - Yalnız hassas-OLMAYAN UI tercihleri: görünen ad, yazı boyutu, hareket,
      yüksek kontrast, tercih edilen hukuk alanları. Soru/cevap/dilekçe BURADA YOK.
    - Anonim kullanıcı bu tabloya hiç ulaşmaz (route 401) → tercihleri yalnız
      tarayıcı localStorage'ında kalır (sunucusuz, veri-minimizasyon).
    """

    __tablename__ = "user_preference"

    sub_hash: str = Field(primary_key=True)
    display_name: str = ""
    text_scale: str = "normal"  # "compact" | "normal" | "large"
    reduce_motion: bool = False
    high_contrast: bool = False
    preferred_domains: list[str] = Field(
        default_factory=list, sa_column=sa.Column(sa.JSON)
    )
    updated_at: datetime = Field(default_factory=_utcnow)
