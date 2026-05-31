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


class UserAccount(SQLModel, table=True):
    """E-posta/şifre ile kayıtlı kullanıcı hesabı (self-serve kayıt + giriş).

    sub = f"user:{email}" → sohbet geçmişi/tercih fingerprint(sub) ile anahtarlanır.
    password_hash = pbkdf2_sha256 (api/passwords.py); ham şifre ASLA saklanmaz.
    email normalize edilir (lowercase + strip) → PK.
    """

    __tablename__ = "user_account"

    email: str = Field(primary_key=True)
    password_hash: str
    name: str = ""
    created_at: datetime = Field(default_factory=_utcnow, index=True)


class Conversation(SQLModel, table=True):
    """Kalıcı sohbet kaydı — kayıtlı kullanıcının geçmişi (cihazlar-arası).

    Not: ADALET artık kayıtlı kullanıcıya sohbet geçmişi sunar (anonim kullanıcı
    tarayıcı localStorage'ında tutar). owner_sub_hash = fingerprint(principal.sub)
    — ham email yerine deterministik parmak izi (kullanıcı kendi geçmişini görür,
    DB sızsa kimlik açığa çıkmaz). Mesaj içeriği zaten PII-mask'li saklanır.
    """

    __tablename__ = "conversation"

    id: str = Field(primary_key=True)  # uuid4().hex
    owner_sub_hash: str = Field(index=True)
    title: str = ""
    domain: str = ""
    message_count: int = 0
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    updated_at: datetime = Field(default_factory=_utcnow, index=True)


class Message(SQLModel, table=True):
    """Tek konuşma turu — user ve assistant satırları ayrı kayıt.

    content: PII-mask'li soru/cevap metni. citations_json: o turda kullanılan
    kaynak listesi (Kaynaklar paneli bunları birleştirir).
    """

    __tablename__ = "message"

    id: str = Field(primary_key=True)  # uuid4().hex
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    turn_index: int = 0
    role: str = "user"  # "user" | "assistant"
    content: str = Field(default="", sa_column=sa.Column(sa.Text))
    domain: str = ""
    citations_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=sa.Column(sa.JSON)
    )
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow, index=True)


class UploadedFile(SQLModel, table=True):
    """OCR yükleme metadata — "Dosyalarım" paneli.

    KVKK veri-minimizasyon: belge METNİ saklanmaz; yalnız metadata (ad, boyut,
    PII bayrağı, hangi sohbet). Kullanıcı belge geçmişini görür, gerekirse
    yeniden yükler.
    """

    __tablename__ = "uploaded_file"

    id: str = Field(primary_key=True)  # uuid4().hex
    owner_sub_hash: str = Field(index=True)
    conversation_id: str = ""
    filename: str = ""
    ocr_engine: str = ""
    n_chars: int = 0
    pii_flag: bool = False
    uploaded_at: datetime = Field(default_factory=_utcnow, index=True)
