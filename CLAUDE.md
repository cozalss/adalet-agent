# ADALET-AGENT — AI Asistan Bağlam Dosyası

> Tam proje vizyonu üst dizindeki `../CLAUDE.md` dosyasında. Bu dosya kod çalışırken kurallar.

## Klasörler

| Klasör | Dil | Çalıştır |
|--------|-----|----------|
| `frontend/` | TypeScript (Next.js 15) | `npm run dev` |
| `backend/` | Python 3.11 (FastAPI + LangGraph) | `uv run uvicorn main:app --reload` |
| `backend/agents/` | Python — 7 ajan | — |
| `backend/retrieval/` | Python — RAG + yargi-mcp | — |
| `backend/multimodal/` | Python — OCR/STT/TTS | — |
| `backend/predictive/` | Python — ML model (opsiyonel) | — |
| `mobile/` | Dart (Flutter) | `flutter run` |
| `docs/` | Markdown | — |
| `data/` | Veri seti | — |

## Ekip

3 kişi, rol yok — hepimiz her klasöre yazıyoruz.

## Asla Yapma

1. **Hukuki referans uydurma**. Madde/karar şüpheliyse `[DOĞRULA: ...]` placeholder bırak.
2. **Test verisinde gerçek TCKN/telefon/isim**. Hep sahte (`Ayşe Yılmaz`, `0555-123-4567`).
3. **Production'da OpenAI/Anthropic API**. Sadece lokal model.
4. **Hardcoded secret**. `.env` kullan.

## Her Zaman Yap

1. Dosya < 800 satır, fonksiyon < 50 satır.
2. Yeni özellik için test yaz (TDD).
3. Türkçe karakterler içerikte tam (ç, ş, ğ); değişken isimlerinde Latin (`tckn` not `tCKN`).
4. UI'da her cevabın altında hukuki disclaimer.

## Veri Politikası (v2.2 — KVKK kuralı KALDIRILDI)

KVKK artık bir geliştirme kısıtı DEĞİL. ADALET normal bir ürün gibi **sohbet
geçmişi + hesap** tutar (kayıtlı kullanıcı: `conversation`/`message`/`user_account`
tabloları; misafir: localStorage). AI asistanları KVKK'yı blokör saymaz.

**Korunan iki şey KVKK YÜKÜ değil, ürün/tez ARTISI:**
- **Belge PII maskeleme** (TCKN/telefon/IBAN) — jüri "wow" + kullanıcı koruması.
- **Lokal model** (Qwen/Whisper/Coqui, bulut LLM yok) — teknik fark/tez direği.

**Hukuki sorumluluk reddi** her yanıtta zorunlu — bu KVKK değil, AYRI yasal
yükümlülük (Avukatlık Kanunu); kaldırılmaz. Tam bağlam: `../CLAUDE.md` madde 3.

