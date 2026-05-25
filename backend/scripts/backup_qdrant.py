"""Qdrant snapshot backup — Sprint-4 W8.3.

Production'da cron (günlük) ile çalıştırılır. Akış:
  1. Tüm collection'lar için snapshot oluştur (Qdrant API)
  2. Snapshot'ı disk'e indir
  3. (Opsiyonel) S3-compatible storage'a yükle
  4. Eski snapshot'ları temizle (BACKUP_RETENTION_DAYS)

Çalıştırma:
  QDRANT_URL=http://qdrant:6333 QDRANT_API_KEY=... \
  BACKUP_DIR=/var/backups/adalet \
    uv run python -m scripts.backup_qdrant

S3 upload (opsiyonel, boto3 gerekli):
  S3_BUCKET=adalet-backups S3_PREFIX=qdrant/staging \
  AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
    uv run python -m scripts.backup_qdrant --s3

Cron örneği (Hetzner staging):
  0 3 * * * /usr/local/bin/docker compose exec backend uv run python -m scripts.backup_qdrant --s3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def _qdrant() -> tuple[str, dict[str, str]]:
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    headers: dict[str, str] = {}
    api_key = os.environ.get("QDRANT_API_KEY")
    if api_key:
        headers["api-key"] = api_key
    return url, headers


def list_collections() -> list[str]:
    url, h = _qdrant()
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{url}/collections", headers=h)
        r.raise_for_status()
        data = r.json()
    return [coll["name"] for coll in data.get("result", {}).get("collections", [])]


def create_snapshot(collection: str) -> str:
    """POST /collections/{collection}/snapshots → snapshot name."""
    url, h = _qdrant()
    with httpx.Client(timeout=300.0) as c:
        r = c.post(f"{url}/collections/{collection}/snapshots", headers=h)
        r.raise_for_status()
        result = r.json().get("result", {})
    return result.get("name", "")


def download_snapshot(collection: str, snapshot_name: str, out_dir: Path) -> Path:
    """GET /collections/{collection}/snapshots/{name} → file."""
    url, h = _qdrant()
    out_path = out_dir / f"{collection}__{snapshot_name}"
    with httpx.stream(
        "GET",
        f"{url}/collections/{collection}/snapshots/{snapshot_name}",
        headers=h, timeout=600.0,
    ) as r:
        r.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                fh.write(chunk)
    return out_path


def cleanup_old(out_dir: Path, retention_days: int) -> int:
    """Eski snapshot'ları sil. Returns: silinmiş dosya sayısı."""
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for p in out_dir.glob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def upload_s3(local_path: Path, bucket: str, prefix: str) -> str:
    """boto3 ile S3'e yükle. Returns: s3 path."""
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        raise RuntimeError("boto3 yok — `uv add boto3`") from None

    s3 = boto3.client("s3")
    key = f"{prefix.rstrip('/')}/{local_path.name}"
    s3.upload_file(str(local_path), bucket, key)
    return f"s3://{bucket}/{key}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Qdrant backup")
    parser.add_argument("--s3", action="store_true", help="S3 upload")
    parser.add_argument("--out", default=os.environ.get("BACKUP_DIR", "data/backups/qdrant"))
    parser.add_argument(
        "--retention",
        type=int,
        default=int(os.environ.get("BACKUP_RETENTION_DAYS", "7")),
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report = {"ts": ts, "snapshots": [], "errors": []}

    try:
        collections = list_collections()
        print(f"[backup] {len(collections)} collection: {collections}")
    except httpx.HTTPError as exc:
        print(f"[backup] FAIL list_collections: {exc}", file=sys.stderr)
        return 2

    for coll in collections:
        try:
            print(f"[backup] {coll}: creating snapshot...")
            name = create_snapshot(coll)
            print(f"[backup]   → {name}")
            local = download_snapshot(coll, name, out_dir)
            entry: dict[str, object] = {
                "collection": coll, "snapshot_name": name,
                "local_path": str(local), "size_bytes": local.stat().st_size,
            }
            if args.s3:
                bucket = os.environ.get("S3_BUCKET")
                prefix = os.environ.get("S3_PREFIX", "qdrant/staging")
                if not bucket:
                    raise ValueError("S3_BUCKET env yok")
                s3_path = upload_s3(local, bucket, prefix)
                entry["s3_path"] = s3_path
                print(f"[backup]   ↑ {s3_path}")
            report["snapshots"].append(entry)
        except Exception as exc:
            print(f"[backup] FAIL {coll}: {exc}", file=sys.stderr)
            report["errors"].append({"collection": coll, "error": str(exc)})

    removed = cleanup_old(out_dir, args.retention)
    report["cleaned_files"] = removed
    print(f"[backup] cleaned {removed} old files (retention={args.retention}d)")

    rep_path = out_dir / f"_report_{ts}.json"
    rep_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[backup] report → {rep_path}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
