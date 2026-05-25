# ADR-006 — PII mask before persist, not after

**Durum:** Accepted
**Tarih:** 2026-05-23
**Sprint:** 4 / W6.4

## Bağlam
KVKK + CLAUDE.md "session persist ve audit log'da PII yok" kuralı. Üç tasarım
seçeneği:

1. **Masking at egress** — kullanıcı sorusu orijinal saklanır, sadece
   log/audit'e yazılırken mask. Kullanıcı erişimi gerekirse orijinal var.
2. **Masking at ingress** — soru API'a girdiği anda mask edilir; LLM'e mask
   edilmiş gider, persist edilmiş mask edilmiş. Geri dönüşümsüz.
3. **Hibrit** — PII LLM'e gider (cevap için gerekebilir), persist'e gitmez.

İhtilaf:
- "TC numaramla işveren neden anlaşamıyor?" sorusunda TC'yi mask edersek
  cevap genelleşir; LLM "TC numaranızla" demez. Bu UX kaybı.
- Aksine "Telefonumla 0555-xxx-xx-xx dolandırıldım" sorusunda
  telefonu loglamak KVKK ihlali.

## Karar
**Hibrit (seçenek 3):**
- LLM'e orijinal soru (PII dahil) gider — kullanıcının kendi verisi, kendi
  bilgisine cevap üretebilsin.
- `session_store.append_turn()` ve `audit.emit()` çağrılarına `safe_for_log =
  mask_pii(question).masked_text` gider. Bunlar production'da Redis +
  Object Storage'a yazılır.
- `hash_question()` SHA-256 fingerprint audit'te question identity için
  (debug için orijinal görmeden trace eşleme).

PII pattern'ları:
- TCKN (11-hane, ilk ≠ 0, lookaround)
- Telefon (TR +90/0xxx, format-tolerant)
- Email, IBAN, Plaka

Mask token: `[PII_MASKED]` (geri-dönüşümsüz).

## Sonuç
W6 sonu 9 PII test green:
- TCKN, phone, email, IBAN, plate her biri ayrı pattern test
- Audit log'da `question_hash` + `question_len` (orijinal len, mask sonrası değil)
- Production'da Filebeat → S3 stream PII-free

## Alternatifler
- **NER-based PII** (spaCy/transformers): false-pos riski Türkçe için yüksek,
  regex pattern coverage zaten dar (5 tip yeterli — beta için).
- **Tokenization** (PII → token, reversible): KVKK denetiminde kullanılabilir
  ama key management ek operasyon — production'a gerek olduğunda eklenir.

## İlgili
- [api/pii.py](../../adalet-agent/backend/api/pii.py)
- [api/routes/ask.py:115-130](../../adalet-agent/backend/api/routes/ask.py#L115)
- [api/audit.py](../../adalet-agent/backend/api/audit.py)
- CLAUDE.md §3 KVKK
