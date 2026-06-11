"""scripts/eval_run.madde_level_metrics — madde-düzeyi retrieval metriği (denetim 2026-06-04).

Headline domain@k/MRR 8-yönlü topic proxy'si MRR'ı abartır (yanlış madde içeren chunk bile
'isabet'). Bu metrik 'DOĞRU maddeyi getirdik mi'yi ölçer. Saf fonksiyon → sentetik chunk
metadata'sıyla Qdrant'sız test edilir.
"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.eval_run import madde_level_metrics


def _chunk(kanun, madde, tur=None):
    meta = {"kanun_kodu": kanun, "madde_no": madde}
    if tur:
        meta["madde_tur"] = tur
    return SimpleNamespace(metadata=meta, text="...")


def test_perfect_madde_at_rank1():
    res = [_chunk("IK", 14), _chunk("IK", 99), _chunk("TBK", 1)]
    m = madde_level_metrics(res, ["IK"], [14])
    assert m["madde_recall@5"] == 1.0
    assert m["madde_mrr"] == 1.0


def test_madde_at_rank3_mrr_third():
    res = [_chunk("IK", 1), _chunk("IK", 2), _chunk("IK", 14)]
    m = madde_level_metrics(res, ["IK"], [14])
    assert m["madde_mrr"] == round(1 / 3, 3)


def test_right_madde_wrong_kanun_not_counted():
    """Doğru madde no AMA yanlış kanun → eşleşme değil (kanun-scoped sıkılık)."""
    res = [_chunk("TBK", 14)]  # beklenen IK m.14, gelen TBK m.14
    m = madde_level_metrics(res, ["IK"], [14])
    assert m["madde_recall@5"] == 0.0
    assert m["madde_mrr"] == 0.0


def test_partial_recall_half():
    res = [_chunk("IK", 14), _chunk("IK", 5)]  # beklenen 14 ve 32; sadece 14 geldi
    m = madde_level_metrics(res, ["IK"], [14, 32])
    assert m["madde_recall@5"] == 0.5


def test_ek_gold_now_measurable_and_tur_scoped():
    """P8: gold 'ek-11' artık ÖLÇÜLÜR (önceden isdigit filtresi sessizce atıyordu)
    ve yalnız madde_tur=ek chunk'la eşleşir — normal m.11 isabet SAYILMAZ."""
    normal_11 = _chunk("VUK", 11)            # madde_tur yok → 'madde'
    ek_11 = _chunk("VUK", 11, tur="ek")
    m_wrong = madde_level_metrics([normal_11], ["VUK"], ["ek-11"])
    assert m_wrong != {} and m_wrong["madde_recall@5"] == 0.0
    m_right = madde_level_metrics([ek_11], ["VUK"], ["ek-11"])
    assert m_right["madde_recall@5"] == 1.0 and m_right["madde_mrr"] == 1.0


def test_mixed_gold_numeric_and_gecici():
    res = [_chunk("IIK", 2, tur="gecici"), _chunk("IIK", 62)]
    m = madde_level_metrics(res, ["IIK"], [62, "gecici-2"])
    assert m["madde_recall@5"] == 1.0
    assert m["n_expected_madde"] == 2.0


def test_empty_expected_madde_excluded():
    assert madde_level_metrics([_chunk("IK", 14)], ["IK"], []) == {}


def test_only_top_k_counts():
    # madde 14 yalnız 6. sırada → top-5 dışında, sayılmaz.
    res = [_chunk("IK", i) for i in (1, 2, 3, 4, 5)] + [_chunk("IK", 14)]
    m = madde_level_metrics(res, ["IK"], [14], k=5)
    assert m["madde_recall@5"] == 0.0


def test_missing_madde_metadata_skipped():
    res = [SimpleNamespace(metadata={"kanun_kodu": "IK"}, text="..."), _chunk("IK", 14)]
    m = madde_level_metrics(res, ["IK"], [14])
    assert m["madde_recall@5"] == 1.0  # eksik-madde chunk atlandı, 2. chunk eşleşti
