"""NLI verifier sanity test — 6 örnek claim.

Çalıştırma:
    uv run python -m scripts.test_verifier

Beklenen:
  Pozitif claim'ler (entailment >= 0.6)  → VERIFIED
  Negatif claim'ler (contradiction)      → REJECTED
  Alakasız claim'ler (neutral)           → REJECTED
"""

from __future__ import annotations

import time

from verifier.nli import get_verifier, is_supported

# (claim, evidence, expected_label)
TEST_CASES: list[tuple[str, str, str]] = [
    # 1. Pozitif — kanıtın doğrudan içinde
    (
        "Tüketici 14 gün içinde malı iade edebilir.",
        "Tüketicinin Korunması Hakkında Kanun Madde 11 uyarınca, mesafeli "
        "sözleşmelerde tüketici 14 gün içinde herhangi bir gerekçe göstermeksizin "
        "ve cezai şart ödemeksizin sözleşmeden cayma hakkına sahiptir.",
        "entailment",
    ),
    # 2. Pozitif — paraphrase
    (
        "İşçi kıdem tazminatı için en az 1 yıl çalışmış olmalıdır.",
        "İş Kanunu 1475 sayılı Kanun'un 14. maddesine göre, en az bir yıl çalışmış "
        "olan işçinin hizmet akdinin feshi halinde, her tam yıl için 30 günlük "
        "ücreti tutarında kıdem tazminatı ödenir.",
        "entailment",
    ),
    # 3. Negatif — kanıtla çelişiyor
    (
        "Kira sözleşmesinde artış oranı serbestçe belirlenir.",
        "Türk Borçlar Kanunu Madde 344 uyarınca, konut ve çatılı işyeri kiralarında "
        "kira bedelinin artış oranı, bir önceki kira yılında tüketici fiyat "
        "endeksindeki on iki aylık ortalamalara göre değişim oranını geçemez.",
        "contradiction",
    ),
    # 4. Alakasız — neutral
    (
        "İcra takibinde haciz prosedürü uygulanır.",
        "Tüketicinin Korunması Hakkında Kanun Madde 11 mesafeli sözleşmelerde "
        "cayma hakkını düzenler.",
        "neutral",
    ),
    # 5. Pozitif — kısa claim, uzun kanıt
    (
        "İhtarname noter aracılığıyla çekilir.",
        "Türk Borçlar Kanunu'nda öngörülen hallerde, alacaklı borcunu temerrüde "
        "düşürmek için noter aracılığıyla bir ihtarname göndermelidir. Bu "
        "ihtarname yazılı şekilde ve tarihi belli olacak biçimde düzenlenir.",
        "entailment",
    ),
    # 6. Uydurmaca madde — verifier yakalayamaz (NLI semantik, fuzzy değil)
    # Bu case fuzzy citation.py'nin kapsamı; burada neutral beklenir.
    (
        "TKHK Madde 999 tüketiciye altın tazminat verir.",
        "Tüketicinin Korunması Hakkında Kanun Madde 11 mesafeli sözleşme.",
        "neutral",
    ),
]


def _label_icon(actual: str, expected: str) -> str:
    return "[OK]" if actual == expected else "[XX]"


def main() -> None:
    print("=" * 70)
    print("NLI VERIFIER SANITY TEST")
    print("=" * 70)
    print("Model: mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
    print("Eşik:  entailment >= 0.60 AND contradiction < 0.30")
    print()

    verifier = get_verifier()

    # Warmup — model yüklemesi süresini ölçmemek için
    print("Warming up (model load)...")
    t0 = time.perf_counter()
    _ = verifier.verify("test", "test cümlesi")
    print(f"  warmup: {(time.perf_counter() - t0) * 1000:.0f} ms")
    print()

    correct = 0
    total = len(TEST_CASES)

    for i, (claim, evidence, expected) in enumerate(TEST_CASES, 1):
        t0 = time.perf_counter()
        result = verifier.verify(claim, evidence)
        elapsed = (time.perf_counter() - t0) * 1000

        supported = is_supported(result)
        icon = _label_icon(result.label, expected)
        if result.label == expected:
            correct += 1

        print(f"[{i}] {icon} expected={expected:13s} got={result.label:13s} "
              f"score={result.score:.2f}  ent={result.entailment_score:.2f}  "
              f"contra={result.contradiction_score:.2f}  ({elapsed:.0f}ms)")
        print(f"     supported_for_rag={supported}")
        print(f"     claim:    {claim[:70]}")
        print(f"     evidence: {evidence[:70]}...")
        print()

    accuracy = correct / total
    print("=" * 70)
    print(f"  ACCURACY: {correct}/{total}  ({accuracy * 100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    main()
