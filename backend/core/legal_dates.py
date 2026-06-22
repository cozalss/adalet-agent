"""Hukuki süre/tarih hesaplayıcı — ajanın 'tool-use' yeteneği (deterministik araç).

Sorun: LLM tarih aritmetiğinde GÜVENİLMEZ (28.02 + 7 gün'ü yanlış sayar, artık yılı kaçırır). Bu
araç kullanıcının sorusundaki TARİHİ + cevaptaki SÜREYİ (örn "itiraz süresi 7 gündür") alıp son
günü KESİN hesaplar. Sıfır halüsinasyon: math deterministik, sonuç "yaklaşık + teyit edin" notuyla
(resmi/adli tatil hariç). Referans: agentic RAG tool-use (LLM karar verir, araç hesaplar).

Kullanım: deadline_note(question, answer) → "" veya hesaplanmış son-gün notu.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}
_UNIT_DAYS = {"gün": 1, "hafta": 7}

# Türkçe kelime-sayılar — hukuki cevaplar süreyi RAKAM değil KELİME yazar ("iki yıl", "altı ay",
# "yedi gün", "on beş gün"). Bileşik ("on beş") alternation'da önce gelmeli (uzun-önce).
_WORD_NUM = {
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8,
    "dokuz": 9, "on beş": 15, "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "altmış": 60, "doksan": 90,
}
_NUM_ALT = r"\d{1,3}|" + "|".join(sorted(_WORD_NUM, key=len, reverse=True))


def extract_date(text: str) -> date | None:
    """Metinden ilk tarihi çıkar: DD.MM.YYYY, DD/MM/YYYY veya '28 Şubat 2024'. Yoksa None."""
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", text or "")
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\s+([a-zçğıöşü]+)\s+(\d{4})\b", (text or "").lower())
    if m and m.group(2) in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def extract_duration(answer: str) -> tuple[int, str] | None:
    """Cevaptaki İLK süreyi çıkar — rakam ('7 gün') VEYA kelime ('iki yıl', 'altı ay', 'on beş gün').

    → (sayı, birim) veya None. Birim Türkçe ek alır ('gündür', 'yıllık'); base birim group(2).
    """
    m = re.search(rf"\b({_NUM_ALT})\s*(gün|hafta|yıl|ay)", (answer or "").lower())
    if not m:
        return None
    num = m.group(1)
    n = int(num) if num.isdigit() else _WORD_NUM.get(num, 0)
    if n <= 0:
        return None
    return n, m.group(2)


def _add_months(d: date, months: int) -> date:
    """Takvim-doğru ay ekleme (gün taşması ay sonuna sabitlenir)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_deadline(start: date, n: int, unit: str) -> date:
    """Başlangıç + süre → son gün (gün/hafta exact; ay/yıl takvim-doğru)."""
    if unit in _UNIT_DAYS:
        return start + timedelta(days=n * _UNIT_DAYS[unit])
    if unit == "ay":
        return _add_months(start, n)
    return _add_months(start, n * 12)  # yıl


def deadline_note(question: str, answer: str) -> str:
    """Soruda tarih + cevapta süre varsa son günü hesapla → kullanıcı-dostu not. Yoksa ''."""
    start = extract_date(question)
    dur = extract_duration(answer)
    if not start or not dur:
        return ""
    n, unit = dur
    if n <= 0 or n > 999:
        return ""
    try:
        end = compute_deadline(start, n, unit)
    except (ValueError, OverflowError):
        return ""
    return (
        f"📅 Girdiğiniz {start.strftime('%d.%m.%Y')} tarihine göre {n} {unit}lık süre yaklaşık "
        f"**{end.strftime('%d.%m.%Y')}** tarihinde dolar (resmî/adli tatil hariç — son gün resmi "
        f"tatile denk gelirse sonraki iş gününe uzayabilir; kritik işlemde mutlaka teyit edin)."
    )


__all__ = ("compute_deadline", "deadline_note", "extract_date", "extract_duration")
