"""Offline gate for multimodal, training, and live integration contracts.

Live credentials/GPU are validated by deployment smoke commands. This gate keeps
the repo honest before that point: endpoints, security guards, Supabase grants,
cloud/local fallbacks, and fast contract tests must all exist.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, snippets: list[str], errors: list[str]) -> None:
    text = read(path)
    for snippet in snippets:
        if snippet not in text:
            errors.append(f"{path}: missing {snippet!r}")


def main() -> int:
    errors: list[str] = []

    require(
        "backend/api/routes/multimodal.py",
        [
            '"/ocr"',
            '"/stt"',
            '"/tts"',
            "MAX_IMAGE_BYTES = 20 * 1024 * 1024",
            "MAX_AUDIO_BYTES = 25 * 1024 * 1024",
            "MAX_TTS_CHARS = 8000",
            "_detect_image_kind",
            "_detect_audio_kind",
            "mask_pii",
            '@limiter.limit("5/minute")',
            '@limiter.limit("10/minute")',
        ],
        errors,
    )

    require(
        "backend/multimodal/ocr.py",
        [
            'OCR_PROVIDER = os.getenv("OCR_PROVIDER", "auto").lower()',
            "OCR_CLOUD_FALLBACK",
            "cloud_ocr_enabled",
            "rapidocr_image",
            "extract_pdf_text",
            "extract_docx_text",
        ],
        errors,
    )
    require(
        "backend/multimodal/stt.py",
        [
            'STT_PROVIDER = os.getenv("STT_PROVIDER", "auto").lower()',
            "STT_CLOUD_FALLBACK",
            "cloud_stt_enabled",
            "STT_NO_SPEECH_PROB_MAX",
            "STT_AVG_LOGPROB_MIN",
            "threading.Lock()",
        ],
        errors,
    )
    require(
        "backend/multimodal/tts.py",
        [
            'TTS_PROVIDER = os.getenv("TTS_PROVIDER", "auto").lower()',
            "TTS_CLOUD_FALLBACK",
            "cloud_tts_enabled",
            "_normalize_for_speech",
            "threading.Lock()",
        ],
        errors,
    )

    require(
        "backend/training/lora_embedding.py",
        [
            "class TrainConfig",
            "class TrainResult",
            "load_triplets",
            "split_train_val",
            "_check_peft_available",
            "train_lora",
        ],
        errors,
    )

    require(
        "supabase/schema.sql",
        [
            "grant select, insert, update, delete on table public.profiles to authenticated",
            "grant select, insert, update, delete on table public.messages to authenticated",
            "revoke execute on function public.save_conversation(text, text, text, jsonb) from anon",
        ],
        errors,
    )
    require(
        "supabase/migrations/0002_explicit_data_api_grants.sql",
        [
            "grant usage on schema public to authenticated",
            "revoke all on table public.uploaded_files from public, anon, authenticated",
            "grant execute on function public.save_conversation(text, text, text, jsonb) to authenticated",
        ],
        errors,
    )

    require(
        "backend/tests/test_multimodal_contract_fast.py",
        [
            "test_detect_image_kind_accepts_supported_magic_bytes",
            "test_detect_audio_kind_accepts_supported_magic_bytes",
            "test_multimodal_limits_are_production_bounded",
        ],
        errors,
    )
    require(
        "backend/tests/test_training_contract_fast.py",
        [
            "test_lora_train_config_contract_is_sane",
            "test_load_triplets_contract_skips_bad_rows",
            "test_split_train_val_contract_is_deterministic",
        ],
        errors,
    )

    if errors:
        print("Live integration contract check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Live integration contract check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
