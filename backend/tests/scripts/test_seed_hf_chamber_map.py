"""seed_hf_yargitay chamber→domain eşleme regresyon testi.

KÖK-NEDEN (2026-06-16): "11. Hukuk Dairesi"→tuketici eşlemesi corpus'a 3.194 ticari
kararı tüketici sanarak sokmuştu. Bu test, 11.HD'nin ARTIK tüketici (veya herhangi
sivil domain) döndürmediğini kilitler — yeniden eklenirse CI yakalar.
"""

from __future__ import annotations

from scripts.seed_hf_yargitay import CHAMBER_TO_DOMAIN, _detect_chamber_domain


def test_11_hd_not_mapped_to_tuketici():
    """11. HD = ticaret dairesi → haritada OLMAMALI (domain=None → atlanır)."""
    assert "11. Hukuk Dairesi" not in CHAMBER_TO_DOMAIN
    txt = "**11. Hukuk Dairesi 2016/19473 E. , 2018/8367 K.** İçtihat Metni marka hükümsüzlüğü"
    chamber, domain = _detect_chamber_domain(txt)
    assert chamber == "11. Hukuk Dairesi"
    assert domain is None  # corpus dışı → seed atlar


def test_13_hd_still_tuketici():
    """13. HD = gerçek tüketici dairesi → korunmalı."""
    assert CHAMBER_TO_DOMAIN.get("13. Hukuk Dairesi") == "tuketici"
    txt = "**13. Hukuk Dairesi 2016/1 E. , 2018/2 K.** ayıplı mal tüketici"
    _, domain = _detect_chamber_domain(txt)
    assert domain == "tuketici"


def test_no_ceza_chamber_in_map():
    """Hiçbir ceza dairesi haritada olmamalı (ceza corpus dışı — kırmızı çizgi)."""
    assert not any("ceza" in k.lower() for k in CHAMBER_TO_DOMAIN)
