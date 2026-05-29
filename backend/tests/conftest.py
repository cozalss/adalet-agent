"""Pytest fixtures — MockLLM reset, sample claims/citations, in-memory state."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Windows: pyarrow'u torch'tan ÖNCE yükle (real-model testleri — embedder/reranker
# sentence_transformers→datasets→pyarrow zinciri torch sonrası çökerdi).
from core import native_preload  # noqa: F401

# Test ortamı: MockLLM zorunlu, HyDE kapalı (network'e gitmesin)
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("HYDE_ENABLED", "0")
os.environ.setdefault("NLI_FP16", "0")
# Sprint-4: LettuceDetect modeli ağır — test'te disabled, fallback yolu kullanır
os.environ.setdefault("LETTUCE_ENABLED", "0")
# ColBERT default kapalı — testlerde Qdrant schema değişmesin
os.environ.setdefault("COLBERT_ENABLED", "0")
os.environ.setdefault("COLBERT_QUERY_ENABLED", "0")
# Sprint-4 W1: production default `PRELOAD_MODELS=1` test'te FastAPI lifespan'ı
# Embedder lazy-load'a sokuyor; Windows + asyncio + torch.cpu segfault yapıyor.
# Test'lerde preload kapalı — mock LLM ile model gerekli değil zaten.
os.environ.setdefault("PRELOAD_MODELS", "0")
# Pre-domain mevzuat boost W1.4 — testlerde kapalı tutuyoruz ki mevzuat_node
# behaviour'u eski testlerde aynı kalsın. Yeni boost testleri kendi env'lerini
# yönetir (`tests/agents/test_mevzuat_node.py`).
os.environ.setdefault("MEVZUAT_DOMAIN_FILTER", "0")
# Mevzuat cross-encoder rerank — testlerde kapalı (BGE-reranker yüklenmesin;
# rerank davranışı kendi testinde fake reranker ile sınanır).
os.environ.setdefault("MEVZUAT_RERANK", "0")
# Uygunluk (eligibility) node — testlerde kapalı ki baseline graph topolojisi
# (mevzuat+emsal→draft) korunsun. Kendi testleri (test_eligibility_node.py) ve
# graph-wiring testi env'i açar. Production/e2e'de default ON.
os.environ.setdefault("ELIGIBILITY_ENABLED", "0")

from agents.llm import reset_llm
from agents.state import Citation, Claim


@pytest.fixture(autouse=True)
def _mock_ragas_embedder(monkeypatch):
    """Sprint-4 W2.5: Ragas answer_relevancy artık (format bug fix sonrası)
    gerçekten Embedder'ı çağırıyor. Windows + asyncio + torch.cpu segfault
    yapar — test'lerde mock cosine ile by-pass.
    """
    try:
        import eval.ragas_full as ragas_mod
    except ImportError:
        return

    def _mock_cosine(reference, candidates):
        # Fake similarity: tüm candidate'lar referansa eşit yakın
        return [0.7] * len(candidates), True

    monkeypatch.setattr(ragas_mod, "_cosine_similarity_batch", _mock_cosine)


@pytest.fixture(autouse=True)
def _reset_llm_singleton() -> Iterator[None]:
    """Her test öncesi/sonrası MockLLM call_count sıfırla."""
    reset_llm()
    yield
    reset_llm()


@pytest.fixture(autouse=True)
def _force_heuristic_predictor(monkeypatch):
    """Testler eğitilmiş BERT checkpoint'ini (varsa) YÜKLEMESİN — hermetic + hızlı.

    train.py lokal bir checkpoint üretirse inference._model_enabled() True olur ve
    predict_outcome torch+model yükler → testler yavaşlar + non-deterministik olur
    (model çıktısı checkpoint'e bağlı). Model-path zaten smoke ile doğrulanıyor;
    testler heuristic'i deterministik test eder. Model-toggle testleri kendi
    monkeypatch'leriyle bunu override edebilir (delenv/setenv).
    """
    monkeypatch.setenv("PREDICTIVE_USE_MODEL", "0")


@pytest.fixture(autouse=True)
def _isolate_feedback_writes(tmp_path, monkeypatch):
    """/feedback endpoint test'lerde gerçek `data/feedback/`'a satır yazmasın.

    Production'da read-only fs altında `/var/lib/adalet/feedback` mount;
    test'te repo-relative `data/feedback` patika kirletilirdi. Burada her
    test için ayrı tmp_path'e yönlendiriyoruz — autouse, import-tolerant.
    """
    try:
        from api.routes import feedback as fb_mod
    except ImportError:
        return
    monkeypatch.setattr(fb_mod, "FEEDBACK_LOG_PATH", tmp_path / "feedback")


@pytest.fixture
def sample_citations() -> list[Citation]:
    """3 örnek citation — TKHK + iş hukuku + emsal karar."""
    return [
        Citation(
            source_id="m-TKHK-11",
            doc_type="law",
            title="TKHK Madde 11",
            snippet=(
                "Tüketici, ayıplı bir mal nedeniyle satıcıdan "
                "sözleşmeden dönmeyi veya satış bedelinden indirim isteme "
                "ya da ayıpsız bir misli ile değiştirilmesini talep edebilir."
            ),
            url="https://mevzuat.gov.tr/madde/TKHK/11",
            score=0.92,
        ),
        Citation(
            source_id="m-IK-32",
            doc_type="law",
            title="İş Kanunu Madde 32",
            snippet=(
                "İşveren, işçinin ücretini en geç ayda bir ödemekle yükümlüdür. "
                "Ödenmediği takdirde işçi haklı sebeple iş akdini feshedebilir."
            ),
            url="https://mevzuat.gov.tr/madde/IK/32",
            score=0.85,
        ),
        Citation(
            source_id="y-9HD-2019-1234",
            doc_type="case",
            title="Yargıtay 9.HD 2019/1234",
            snippet=(
                "Davacı işçinin kıdem tazminatına hak kazanması için "
                "iş akdinin en az bir yıl sürmüş olması ve haklı nedenle "
                "feshedilmiş olması gerekmektedir."
            ),
            url="https://yargi.gov.tr/karar/2019/1234",
            score=0.78,
        ),
    ]


@pytest.fixture
def sample_claims() -> list[Claim]:
    """3 örnek claim — biri TKHK m.11 ile uyumlu, biri uydurma."""
    return [
        Claim(
            text=(
                "Tüketici ayıplı malda sözleşmeden dönme veya bedel indirimi "
                "talep edebilir [src: m-TKHK-11]"
            ),
            cite_ids=["m-TKHK-11"],
            verified=False,
            verify_score=0.0,
            verify_reason="",
        ),
        Claim(
            text="İşçi ücretini ayda bir alır [src: m-IK-32]",
            cite_ids=["m-IK-32"],
            verified=False,
            verify_score=0.0,
            verify_reason="",
        ),
        # Uydurma: TKHK Madde 999 (gerçekte yok)
        Claim(
            text=(
                "TKHK Madde 999 uyarınca tüketici 5 katı tazminat alır "
                "[src: m-TKHK-11]"
            ),
            cite_ids=["m-TKHK-11"],
            verified=False,
            verify_score=0.0,
            verify_reason="",
        ),
    ]


@pytest.fixture
def base_state(sample_citations, sample_claims) -> dict:
    """Verify/debate node'larının çağrılabileceği minimum state."""
    return {
        "question": "Ayıplı malda tüketici hakları nedir?",
        "want_dilekce": False,
        "user_meta": {},
        "domain": "tuketici",
        "domain_confidence": 0.85,
        "triage_reasoning": "Tüketici hukuku — ayıplı mal",
        "mevzuat_refs": sample_citations[:2],
        "emsal_refs": [sample_citations[2]],
        "draft_response": "Mock taslak cevap [src: m-TKHK-11]",
        "claims": sample_claims,
        "verified_claims": [],
        "debate_verdict": "pass",
        "debate_notes": "",
        "retry_count": 0,
        "response": "",
        "confidence": 0.0,
        "disclaimers": [],
        "errors": [],
    }
