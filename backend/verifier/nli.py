"""NLI tabanlı claim doğrulayıcı — multilingual mDeBERTa XNLI.

Bir LLM iddiası verildiğinde:
  premise:    Qdrant'tan getirilen TKHK Madde 11 chunk metni
  hypothesis: "Tüketici 30 gün içinde malı iade edebilir"

Soru: premise hypothesis'i destekliyor (entail) mu? Üç sınıf:
  - entailment   → claim doğru, kanıtlanmış
  - neutral      → kanıt yok ama çelişki de yok
  - contradiction → claim yanlış / kaynakla çelişiyor

Model: MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
  • 100+ dil destekli (Türkçe dahil)
  • ~280 MB, FP16'da ~150 MB GPU
  • <100 ms/inference (RTX 4070)
  • id2label: {0: entailment, 1: neutral, 2: contradiction}

Doğru kullanım: AutoModelForSequenceClassification + tokenizer(premise, hypothesis).
Zero-shot pipeline DEĞİL — bu model doğrudan NLI cross-encoder olarak çalışır.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

import structlog

log = structlog.get_logger()

# Env override (NLI_MODEL) — verifier ile cache namespace TEK kaynaktan beslensin
# (denetim #12: eskiden env yalnız cache'te okunuyordu, model burada sabitten seçilince
# namespace gerçek modeli yansıtmıyordu). Set edilmezse varsayılan mDeBERTa XNLI.
NLI_MODEL = os.getenv("NLI_MODEL", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")

NLILabel = Literal["entailment", "neutral", "contradiction"]
# Modelin id2label sırası (mDeBERTa XNLI standartı)
_ID2LABEL: dict[int, NLILabel] = {0: "entailment", 1: "neutral", 2: "contradiction"}


@dataclass(slots=True)
class NLIResult:
    label: NLILabel
    score: float                 # seçilen etiketin softmax skoru
    entailment_score: float
    neutral_score: float
    contradiction_score: float


class NLIVerifier:
    """Cross-encoder NLI singleton."""

    def __init__(self, model_name: str = NLI_MODEL, use_fp16: bool = True) -> None:
        self.model_name = model_name
        self.use_fp16 = use_fp16
        # verify_batch artık verify_node'da asyncio.to_thread ile çağrılıyor.
        # Eşzamanlı /ask request'leri aynı mDeBERTa modeline ayrı thread'lerden
        # girmesin diye serialize ediyoruz (transformers forward + ilk yükleme
        # thread-safe değil). threading.Lock — kilit worker thread'ler arası.
        self._infer_lock = threading.Lock()

    @cached_property
    def _components(self):
        """Lazy-load tokenizer + model. cuda varsa GPU + fp16.

        NLI_MODEL bir PEFT-adapter dizini ise (adapter_config.json içerir, FAZ 3.1
        TR-legal LoRA) base mDeBERTa XNLI yüklenip adapter merge edilir → sayısal-
        çıkarım fine-tune'u production'a sıfır-mimari değişiklikle girer. Aksi halde
        düz model yükleme (mevcut davranış birebir).
        """
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if (self.use_fp16 and device == "cuda") else torch.float32

        adapter_cfg = os.path.join(self.model_name, "adapter_config.json")
        is_adapter = os.path.isdir(self.model_name) and os.path.isfile(adapter_cfg)
        log.info("nli_loading", model=self.model_name, device=device,
                 dtype=str(dtype), peft_adapter=is_adapter)

        if is_adapter:
            import json as _json

            from peft import PeftModel
            with open(adapter_cfg, encoding="utf-8") as fh:
                base_name = _json.load(fh).get("base_model_name_or_path", NLI_MODEL)
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            base = AutoModelForSequenceClassification.from_pretrained(base_name, dtype=dtype)
            # merge_and_unload: adapter'ı base'e kaynaştır → inference'ta PEFT overhead yok,
            # mevcut forward/cache yolu AYNEN (NLIResult/eşik/namespace değişmez).
            model = PeftModel.from_pretrained(base, self.model_name).merge_and_unload()
            model = model.to(device)
        else:
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name, dtype=dtype,
            ).to(device)
        model.eval()
        return tokenizer, model, device

    def verify(self, claim: str, evidence: str) -> NLIResult:
        """Tek bir (claim=hypothesis, evidence=premise) çiftini sınıflandır."""
        import torch

        if not claim.strip() or not evidence.strip():
            return NLIResult("neutral", 0.0, 0.0, 1.0, 0.0)

        with self._infer_lock:
            tokenizer, model, device = self._components

            # NLI pair: (premise, hypothesis) — modelin beklediği sıra.
            # truncation="only_first": yalnız premise (evidence) kesilir, claim
            # (hypothesis) HER ZAMAN tam kalır. "True" (=longest_first) uzun
            # claim'lerde hipotezi kesip anlamını bozabilirdi — NLI'da hipotez
            # bütünlüğü kritik.
            inputs = tokenizer(
                evidence, claim,
                return_tensors="pt",
                truncation="only_first",
                max_length=512,
                padding=True,
            ).to(device)

            with torch.no_grad():
                logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0].float().cpu().tolist()

        ent, neu, con = probs[0], probs[1], probs[2]
        top_idx = int(max(range(3), key=lambda i: probs[i]))
        return NLIResult(
            label=_ID2LABEL[top_idx],
            score=float(probs[top_idx]),
            entailment_score=float(ent),
            neutral_score=float(neu),
            contradiction_score=float(con),
        )

    def verify_batch(
        self, pairs: list[tuple[str, str]], batch_size: int = 8,
    ) -> list[NLIResult]:
        """Çoklu (claim, evidence) çiftini batch'le — GPU'da çok daha hızlı."""
        import torch

        if not pairs:
            return []

        results: list[NLIResult] = []

        with self._infer_lock:
            tokenizer, model, device = self._components

            for i in range(0, len(pairs), batch_size):
                batch = pairs[i : i + batch_size]
                premises = [e for _, e in batch]
                hypotheses = [c for c, _ in batch]
                inputs = tokenizer(
                    premises, hypotheses,
                    return_tensors="pt", truncation="only_first",
                    max_length=512, padding=True,
                ).to(device)

                with torch.no_grad():
                    logits = model(**inputs).logits
                probs = torch.softmax(logits, dim=-1).float().cpu().tolist()

                for p in probs:
                    ent, neu, con = p[0], p[1], p[2]
                    top_idx = int(max(range(3), key=lambda i: p[i]))
                    results.append(NLIResult(
                        label=_ID2LABEL[top_idx],
                        score=float(p[top_idx]),
                        entailment_score=float(ent),
                        neutral_score=float(neu),
                        contradiction_score=float(con),
                    ))
        return results


_singleton: NLIVerifier | None = None


def get_verifier() -> NLIVerifier:
    global _singleton
    if _singleton is None:
        use_fp16 = os.environ.get("NLI_FP16", "1") != "0"
        _singleton = NLIVerifier(use_fp16=use_fp16)
    return _singleton


def is_contradicted(result: NLIResult, threshold: float = 0.40) -> bool:
    """NLI modelinin çelişki sinyali — claim KAYNAK İLE ÇELİŞİYOR mu?

    Bu modelin asıl gücü: yalanları yakalamak ("TKHK Madde 999 altın tazminat
    verir" → contradiction 0.96). Pozitif paraphrase doğrulamada zayıf
    (Türkçe hukuk dilinde XNLI çok sıkı), bu yüzden iki katmanlı:

      Katman 1 (citation.py): madde-no fuzzy match → POZİTİF onay
      Katman 2 (bu fonksiyon): NLI contradiction filter → NEGATİF veto

    is_contradicted=True olan claim'i finalize'a sızdırma — yalan.
    """
    return result.contradiction_score >= threshold


def is_supported(result: NLIResult, ent_threshold: float = 0.40) -> bool:
    """NLI tek başına yeterli mi? Entailment yüksek + çelişki düşük olmalı.

    NOT: Türkçe hukuk paraphrase'inde XNLI sıkı kalır. Pozitif doğrulama için
    citation.py fuzzy match'i tercih et; bu fonksiyon yalnız 'belirgin entail'
    için. Belirsiz claim'ler citation.py'ye düşer.
    """
    return (
        result.entailment_score >= ent_threshold
        and result.contradiction_score < 0.20
    )
