"""Hukuki tarih/süre hesaplayıcı (tool-use) — tarih/süre çıkarımı + deterministik son-gün."""
from __future__ import annotations

from datetime import date

from core.legal_dates import (
    compute_deadline,
    deadline_note,
    extract_date,
    extract_duration,
)


def test_extract_date_numeric():
    assert extract_date("Ödeme emrini 28.02.2024 tarihinde aldım") == date(2024, 2, 28)
    assert extract_date("tebliğ 5/3/2023 oldu") == date(2023, 3, 5)


def test_extract_date_turkish_month():
    assert extract_date("kararı 1 Mart 2024 günü öğrendim") == date(2024, 3, 1)
    assert extract_date("15 Ağustos 2022 tarihli") == date(2022, 8, 15)


def test_extract_date_none_and_invalid():
    assert extract_date("tarih yok burada") is None
    assert extract_date("32.13.2024 geçersiz") is None


def test_extract_duration():
    assert extract_duration("itiraz süresi 7 gündür") == (7, "gün")
    assert extract_duration("cevap için 2 hafta") == (2, "hafta")
    assert extract_duration("1 ay içinde") == (1, "ay")
    assert extract_duration("zamanaşımı 10 yıl") == (10, "yıl")
    assert extract_duration("süre belirtilmemiş") is None


def test_extract_duration_turkish_words():
    """Hukuki cevaplar süreyi KELİME yazar — bunlar da yakalanmalı (gerçek cevap deseni)."""
    assert extract_duration("teslim tarihinden itibaren iki yıl içinde haklar kullanılır") == (2, "yıl")
    assert extract_duration("ayıp ihbarı altı ay içinde yapılır") == (6, "ay")
    assert extract_duration("itiraz süresi yedi gündür") == (7, "gün")
    assert extract_duration("temyiz süresi on beş gün olarak belirlenmiştir") == (15, "gün")  # bileşik


def test_extract_duration_skips_work_and_past():
    """Workflow HIGH bulgusu: çalışma-süresi/geçmiş-zaman YANLIŞ deadline olmamalı."""
    # çalışma-süresi 'yıllık' atlanmalı, gerçek deadline 'ihbar süresi 8 hafta' alınmalı
    assert extract_duration(
        "5 yıllık çalışma için kıdem tazminatı hakkınız var; ihbar süresi 8 haftadır") == (8, "hafta")
    # geçmiş-zaman '5 yıl önce' atlanmalı; '30 gün' başvuru süresi alınmalı
    assert extract_duration("5 yıl önce aldığınız ürün için başvuru süresi 30 gündür") == (30, "gün")
    # kıdem/çalışma bağlamı tek başına → deadline DEĞİL
    assert extract_duration("2 yıldır çalışıyorsunuz, kıdem tazminatına hak kazandınız") is None


def test_extract_duration_requires_deadline_context():
    """Bağlamsız çıplak süre → None (muhafazakâr; yanlış-pozitif yok)."""
    assert extract_duration("evde 3 yıl oturdu") is None          # bağlam yok
    assert extract_duration("itiraz süresi 7 gün") == (7, "gün")  # 'süresi' bağlamı var


def test_deadline_note_vowel_harmony():
    """Workflow bulgusu: 'günlık' YANLIŞ → 'günlük' olmalı (ses uyumu)."""
    note = deadline_note("28.02.2024 aldım", "itiraz süresi 7 gündür")
    assert "günlük" in note and "günlık" not in note


def test_deadline_note_no_false_positive_from_work_duration():
    """Uçtan uca HIGH senaryosu: çalışma-süresi yanlış son-tarih ÜRETMEMELİ."""
    note = deadline_note(
        "10.01.2022 tarihinde işten çıkarıldım, 5 yıldır çalışıyordum",
        "5 yıllık çalışma için kıdem hakkınız var; ihbar süresi 8 haftadır.")
    # 8 hafta'dan hesaplanmalı (10.01.2022 + 56 gün = 07.03.2022), 5 yıl'dan (2027) DEĞİL
    assert "2027" not in note and "07.03.2022" in note


def test_compute_deadline_days_exact():
    # 28.02.2024 + 7 gün → 06.03.2024 (2024 ARTIK YIL: şubat 29 çeker — LLM'in kaçırdığı)
    assert compute_deadline(date(2024, 2, 28), 7, "gün") == date(2024, 3, 6)
    assert compute_deadline(date(2023, 2, 28), 7, "gün") == date(2023, 3, 7)  # 2023 normal


def test_compute_deadline_weeks_months_years():
    assert compute_deadline(date(2024, 1, 1), 2, "hafta") == date(2024, 1, 15)
    assert compute_deadline(date(2024, 1, 31), 1, "ay") == date(2024, 2, 29)  # gün taşması ay sonuna
    assert compute_deadline(date(2024, 3, 15), 1, "yıl") == date(2025, 3, 15)


def test_deadline_note_full():
    note = deadline_note("28.02.2024 tarihinde aldım", "itiraz süresi 7 gündür")
    assert "06.03.2024" in note and "28.02.2024" in note and "teyit" in note


def test_deadline_note_missing_parts():
    assert deadline_note("28.02.2024 aldım", "süre yok") == ""      # süre yok
    assert deadline_note("tarih yok", "7 gün süre var") == ""        # tarih yok
    assert deadline_note("", "") == ""
