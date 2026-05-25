"""Deprecated shim — use ``python -m scripts.seed`` instead.

Eski monolitik seed.py yerine artık scripts/seed/ package'i var. Bu dosya
geriye uyumluluk için duruyor, asıl CLI:

    uv run python -m scripts.seed --help
"""

from __future__ import annotations

import sys

from scripts.seed.__main__ import main

if __name__ == "__main__":
    print(
        "[deprecated] scripts/seed.py yerine 'python -m scripts.seed' kullanın",
        file=sys.stderr,
    )
    sys.exit(main(sys.argv[1:]))
