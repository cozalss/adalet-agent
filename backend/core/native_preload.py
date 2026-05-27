"""Windows native import-order guard — pyarrow'u torch'tan ÖNCE yükle.

Bu Windows kutusunda Arrow (pyarrow) ile torch'un native runtime'ları import
SIRASINA duyarlı. torch önce yüklenirse, sonradan gelen `import pyarrow`
(sentence_transformers → datasets → pyarrow zinciriyle) **access violation**
ile tüm Python sürecini sessizce çökertir (exit 0, traceback yok). pyarrow EN
BAŞTA import edilirse Arrow native runtime'ı önce kurulur ve çakışma olmaz.

Belirti (bu modül yokken): `Embedder().encode(...)` veya reranker yüklemesi
süreci öldürür; `freeze_baseline` / canlı /ask retrieval aşamasında patlar.
Kök neden faulthandler ile bulundu: `pyarrow/__init__.py` import'unda
"Windows fatal exception: access violation".

Kullanım: süreç girişlerinde (main.py, conftest.py, eval scriptleri) torch
DOLAYLI olarak yüklenmeden ÖNCE ilk import'lardan biri bu olmalı:

    from core import native_preload  # noqa: F401

Linux/Docker'da gereksiz ama zararsız; `DISABLE_PYARROW_PRELOAD=1` ile kapatılır.
"""

from __future__ import annotations

import contextlib
import os

if os.getenv("DISABLE_PYARROW_PRELOAD", "0").lower() not in {"1", "true", "yes"}:
    # pyarrow yoksa/farklı ortamsa sessiz geç — torch yine de çalışır.
    with contextlib.suppress(Exception):
        import pyarrow.dataset  # noqa: F401  — yalnız yan-etki: Arrow native init
