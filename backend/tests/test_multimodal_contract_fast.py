"""Fast multimodal contract tests included in the main backend suite.

The heavier real STT/TTS/OCR integration tests still live under tests/multimodal.
These tests keep the endpoint security/format contract covered without model
downloads, GPU, ffmpeg execution, or network.
"""

from __future__ import annotations

from api.routes import multimodal as mm


def test_detect_image_kind_accepts_supported_magic_bytes() -> None:
    assert mm._detect_image_kind(b"\xff\xd8\xff" + b"\x00" * 16) == "jpeg"
    assert mm._detect_image_kind(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16) == "png"
    assert mm._detect_image_kind(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8) == "webp"
    assert mm._detect_image_kind(b"%PDF-" + b"\x00" * 16) == "pdf"
    assert mm._detect_image_kind(b"not-a-real-image") is None


def test_detect_audio_kind_accepts_supported_magic_bytes() -> None:
    assert mm._detect_audio_kind(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8) == "wav"
    assert mm._detect_audio_kind(b"OggS" + b"\x00" * 16) == "ogg"
    assert mm._detect_audio_kind(b"fLaC" + b"\x00" * 16) == "flac"
    assert mm._detect_audio_kind(b"\x1aE\xdf\xa3" + b"\x00" * 16) == "webm"
    assert mm._detect_audio_kind(b"\x00" * 4 + b"ftyp" + b"\x00" * 8) == "mp4"
    assert mm._detect_audio_kind(b"ID3" + b"\x00" * 16) == "mp3"
    assert mm._detect_audio_kind(b"not-real-audio") is None


def test_sanitize_filename_blocks_path_components_and_controls() -> None:
    assert mm._sanitize_filename("../../etc/passwd") == "passwd"
    assert mm._sanitize_filename("..\\..\\evil\x00.png") == "evil.png"
    assert mm._sanitize_filename("çalışma belgesi.pdf") == "al__ma_belgesi.pdf"
    assert mm._sanitize_filename("") == "upload"


def test_base_mime_strips_browser_codec_parameters() -> None:
    assert mm._base_mime("audio/webm;codecs=opus") == "audio/webm"
    assert mm._base_mime(" IMAGE/PNG ") == "image/png"
    assert mm._base_mime(None) == ""


def test_multimodal_limits_are_production_bounded() -> None:
    assert mm.MAX_IMAGE_BYTES == 20 * 1024 * 1024
    assert mm.MAX_AUDIO_BYTES == 25 * 1024 * 1024
    assert mm.MAX_TTS_CHARS == 8000
    assert "application/pdf" in mm._ALLOWED_IMAGE_MIMES
    assert "audio/webm" in mm._ALLOWED_AUDIO_MIMES
