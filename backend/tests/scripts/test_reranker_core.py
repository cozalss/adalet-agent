"""scripts/reranker/_core.py — saf çekirdek testleri (ağ/model GEREKMEZ).

Kapsam-filtresi (ceza/aile ELE — kırmızı çizgi), few-shot prompt yapısı, sentez
temizleme, round-trip kararı, dedup, etiketli-çift, split. Hermetic + hızlı.
"""

from __future__ import annotations

from scripts.reranker._core import (
    CIVIL_DOMAINS,
    QAPair,
    build_synth_messages,
    clean_synth_query,
    dedup_pairs,
    is_out_of_scope,
    labeled_pairs_from_mined,
    roundtrip_keep,
    split_train_val,
    tag_domain,
)

# --- Kapsam filtresi (KIRMIZI ÇİZGİ: ceza + aile ELENMELİ) ---


def test_civil_domains_are_eight():
    assert len(CIVIL_DOMAINS) == 8
    assert "tuketici" in CIVIL_DOMAINS and "idari" in CIVIL_DOMAINS


def test_out_of_scope_drops_ceza():
    assert is_out_of_scope("Sanık hakkında hapis cezası verilmesi talep edildi.")
    assert is_out_of_scope("TCK madde 157 dolandırıcılık suçundan iddianame.")


def test_out_of_scope_drops_aile():
    assert is_out_of_scope("Boşanma davasında nafaka ve velayet talebi.")
    assert is_out_of_scope("Evlilik birliğinin temelinden sarsılması nedeniyle boşanma.")


def test_in_scope_keeps_civil_para_cezasi():
    # 'ceza' kelimesi geçse de idari/trafik/vergi para cezası SİVİL → tutulmalı.
    assert not is_out_of_scope("İdari para cezasına karşı iptal davası açılabilir.")
    assert not is_out_of_scope("Trafik cezasına itiraz süresi nedir?")
    assert not is_out_of_scope("Vergi ziyaı cezası ve usulsüzlük cezası tahakkuk etti.")


def test_in_scope_keeps_eight_civil_domains():
    for txt in [
        "Kiracı depozitosunu geri istiyor.",
        "İşçi kıdem tazminatına hak kazandı.",
        "Ayıplı malın iadesi ve cayma hakkı.",
        "İcra takibinde haciz uygulandı.",
        "Trafik kazasında değer kaybı tazminatı.",
        "KDV iadesi ve vergi beyannamesi.",
        "Tapuda ortaklığın giderilmesi davası.",
        "Belediyenin idari işlemine iptal davası.",
    ]:
        assert not is_out_of_scope(txt), txt


def test_tag_domain_detects_kira_and_is():
    assert tag_domain("Ev sahibim kira kontratı bitince tahliye istiyor, depozito") == "kira"
    assert tag_domain("İşveren kıdem ve ihbar tazminatı ödemeden işçiyi çıkardı") == "isHukuku"


def test_tag_domain_unknown_is_genel():
    assert tag_domain("Bugün hava çok güzel ve deniz sakin.") == "genel"


# --- Few-shot synth prompt ---


def test_build_synth_messages_structure():
    msgs = build_synth_messages("Borçlar Hukuku – kira – güvence bedeli iadesi konusu metni")
    assert msgs[0]["role"] == "system"
    # system + 3 few-shot çift (user+assistant) + 1 son user = 8 mesaj
    assert len(msgs) == 1 + 2 * 3 + 1
    assert msgs[-1]["role"] == "user"
    assert "Konu:" in msgs[-1]["content"]


def test_build_synth_messages_truncates_topic():
    long_doc = "kira " * 1000
    msgs = build_synth_messages(long_doc, topic_chars=100)
    assert len(msgs[-1]["content"]) <= len("Konu: ") + 100


# --- Sentez çıktısı temizleme ---


def test_clean_synth_query_accepts_colloquial():
    q = clean_synth_query("Kiraladığım evden çıktım, depozitomu vermiyorlar ne yapmalıyım?",
                          "mecur güvence bedeli iadesi borçlar kanunu")
    assert q and q.startswith("Kiraladığım")


def test_clean_synth_query_rejects_too_short():
    assert clean_synth_query("Ne yapmalıyım?", "uzun belge metni burada") is None


def test_clean_synth_query_rejects_madde_jargon():
    assert clean_synth_query(
        "Borçlar Kanunu madde 299 uyarınca kiracının hakları nelerdir acaba?",
        "kira sözleşmesi") is None


def test_clean_synth_query_rejects_foreign_script():
    # Qwen dil kayması — Çince karakter içeren çıktı reddedilmeli (gerçek demo bug'ı).
    assert clean_synth_query(
        "Tapumu iptal ettirdiler, ancak bana ilgili 期限不超过60天 ne yapmalıyım?",
        "tapu iptali sicil kaydı") is None
    # Kiril de reddedilir
    assert clean_synth_query("Аракам çarpıldı sigorta ödemiyor ne yaparım acaba?",
                             "trafik kazası") is None


def test_clean_synth_query_accepts_pure_turkish_with_special_chars():
    # Türkçe özel karakterler (çğıöşü) yabancı-alfabe sayılMAZ.
    q = clean_synth_query("İşyerimden çıkarıldım, kıdem tazminatımı alabilir miyim ağabey?",
                          "iş hukuku kıdem tazminatı")
    assert q is not None


def test_clean_synth_query_rejects_copied_document():
    doc = "mecurun erken tahliyesi ihbar öneline uymaksızın güvence bedeli iadesi talebi"
    # Belgeyi neredeyse birebir kopyalamış → AT
    assert clean_synth_query(
        "mecurun erken tahliyesi ihbar öneline uymaksızın güvence bedeli iadesi", doc) is None


def test_clean_synth_query_strips_quotes_and_first_line():
    q = clean_synth_query('"Arabama çarptılar, sigorta ödemiyor, ne yapabilirim?"\nAçıklama: ...',
                          "trafik kazası değer kaybı")
    assert q == "Arabama çarptılar, sigorta ödemiyor, ne yapabilirim?"


def test_clean_synth_query_empty_is_none():
    assert clean_synth_query("", "doc") is None
    assert clean_synth_query("   ", "doc") is None


# --- Round-trip filtre ---


def test_roundtrip_keep_true_when_source_in_topk():
    assert roundtrip_keep("doc-5", ["doc-1", "doc-5", "doc-9"], top_k=10)


def test_roundtrip_keep_false_when_source_absent():
    assert not roundtrip_keep("doc-5", ["doc-1", "doc-2", "doc-3"], top_k=10)


def test_roundtrip_keep_respects_topk_cutoff():
    # Kaynak 11. sırada ama top_k=10 → AT
    ids = [f"doc-{i}" for i in range(11)] + ["doc-target"]
    assert not roundtrip_keep("doc-target", ids, top_k=10)


# --- Dedup + etiketli-çift + split ---


def _pair(qid, q, pid):
    return QAPair(query_id=qid, query=q, pos_id=pid, pos_text="x", domain="kira", source="formal")


def test_dedup_pairs_removes_same_query_pos():
    pairs = [_pair("1", "Aynı soru", "p1"), _pair("2", "aynı soru", "p1"), _pair("3", "Farklı", "p2")]
    out = dedup_pairs(pairs)
    assert len(out) == 2  # ilk iki (case-insensitive aynı) → tek


def test_labeled_pairs_from_mined_labels():
    rows = labeled_pairs_from_mined("soru", "pozitif metin", ["neg1", "neg2"])
    assert rows[0] == {"query": "soru", "passage": "pozitif metin", "label": 1.0}
    assert all(r["label"] == 0.0 for r in rows[1:])
    assert len(rows) == 3


def test_labeled_pairs_no_negatives_only_positive():
    rows = labeled_pairs_from_mined("soru", "pozitif", [])
    assert len(rows) == 1 and rows[0]["label"] == 1.0


def test_split_train_val_deterministic():
    rows = list(range(100))
    t1, v1 = split_train_val(rows, val_frac=0.1, seed=42)
    t2, v2 = split_train_val(rows, val_frac=0.1, seed=42)
    assert (t1, v1) == (t2, v2)  # deterministik
    assert len(v1) == 10 and len(t1) == 90
    assert set(t1) | set(v1) == set(rows)  # kayıp yok


def test_split_train_val_empty():
    assert split_train_val([]) == ([], [])


def test_split_train_val_min_one_val():
    train, v = split_train_val([1, 2, 3], val_frac=0.01)
    assert len(v) == 1
    assert len(train) == 2
