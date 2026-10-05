"""Publish the static files to Cloudflare R2 (bucket benrispace-static).

    python scripts/publish_static.py --dry-run
    python scripts/publish_static.py                       # scores (+ area scores if built)
    python scripts/publish_static.py --tiles build/tiles/benrispace.pmtiles
    python scripts/publish_static.py --scores-only         # what CI runs after scoring
    python scripts/publish_static.py --setup-bucket        # CORS rule, once
    python scripts/publish_static.py --prune --yes         # delete unreferenced files > 7 days

Objects are immutable and content-addressed (`scores/<version>.<sha12>.bin`, ...), so an
upload only happens when head_object says the key is missing. `manifest.json` is written
LAST (a short max-age), merged with the one already in the bucket so entries that are not
being republished stay. The file formats and the manifest are specified in
docs/ARCHITECTURE.md ("Static files on R2").

Credentials: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID (env or .env). The score
file is built from DATABASE_URL in a READ-ONLY session unless --scores PATH is given.
"""

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUCKET = "benrispace-static"
MANIFEST_KEY = "manifest.json"
MANIFEST_FORMAT = 1
MANIFEST_CACHE = "public, max-age=60"
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
PRUNE_MIN_AGE = timedelta(days=7)
PREFIXES = ("scores/", "areas/", "tiles/")
CORS_ORIGINS = [
    "https://benrispace.com",
    "https://www.benrispace.com",
    "https://*.amplifyapp.com",
    "http://localhost:3000",
]
CORS_RULES = {
    "CORSRules": [
        {
            "AllowedMethods": ["GET", "HEAD"],
            "AllowedOrigins": CORS_ORIGINS,
            "AllowedHeaders": ["Range", "If-Match", "If-None-Match"],
            "ExposeHeaders": ["ETag", "Content-Length", "Content-Range", "Accept-Ranges"],
            "MaxAgeSeconds": 86400,
        }
    ]
}


# --- pure parts (tests/test_publish_static.py) ---------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_key(kind: str, version: str, sha: str) -> str:
    """The immutable key for a manifest entry kind: scores | areaScores | tiles."""
    short = sha[:12]
    if kind == "scores":
        return f"scores/{version}.{short}.bin"
    if kind == "areaScores":
        return f"areas/{version}.{short}.bin"
    if kind == "tiles":
        return f"tiles/benrispace.{short}.pmtiles"
    raise ValueError(f"unknown kind {kind!r}")


def entry(kind: str, version: str, data: bytes) -> dict:
    sha = sha256_hex(data)
    return {"path": object_key(kind, version, sha), "bytes": len(data), "sha256": sha}


def put_args(key: str, body: bytes) -> tuple[bytes, dict]:
    """(body to send, put_object kwargs) for an immutable object: .bin files are gzipped with
    Content-Encoding gzip, .pmtiles go up raw so range requests work."""
    if key.endswith(".pmtiles"):
        return body, {
            "ContentType": "application/vnd.pmtiles",
            "CacheControl": IMMUTABLE_CACHE,
        }
    return gzip.compress(body, compresslevel=9, mtime=0), {
        "ContentType": "application/octet-stream",
        "ContentEncoding": "gzip",
        "CacheControl": IMMUTABLE_CACHE,
    }


def merge_manifest(
    existing: dict | None, updates: dict[str, dict], version: str, now: datetime
) -> dict:
    """The new manifest: `updates` (kind -> entry) over the existing one. Entries that are not
    republished are kept, except scores and areaScores from a different weights version."""
    kept = {}
    if existing and existing.get("format") == MANIFEST_FORMAT:
        same_version = existing.get("weightsVersion") == version
        for kind in ("scores", "areaScores", "tiles"):
            if kind in existing and (kind == "tiles" or same_version):
                kept[kind] = existing[kind]
    kept.update(updates)
    return {
        "format": MANIFEST_FORMAT,
        "weightsVersion": version,
        "generatedAt": now.isoformat(timespec="seconds"),
        **{k: kept[k] for k in ("scores", "areaScores", "tiles") if k in kept},
    }


def referenced_keys(manifest: dict | None) -> set[str]:
    if not manifest:
        return set()
    return {manifest[k]["path"] for k in ("scores", "areaScores", "tiles") if k in manifest}


def prune_candidates(
    objects: list[tuple[str, datetime]], manifest: dict | None, now: datetime
) -> list[str]:
    """Keys of immutable objects the manifest does not reference and that are over 7 days old."""
    keep = referenced_keys(manifest)
    return sorted(
        key
        for key, modified in objects
        if key.startswith(PREFIXES) and key not in keep and now - modified > PRUNE_MIN_AGE
    )


# --- R2 and the build -----------------------------------------------------------------


def client():
    import boto3
    from botocore.config import Config
    from dotenv import load_dotenv

    load_dotenv()
    account = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )


def exists(s3, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def read_manifest(s3) -> dict | None:
    from botocore.exceptions import ClientError

    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=MANIFEST_KEY)["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def build_score_file(version: str) -> bytes:
    """The GET /v1/map/scores body, from the scores table in a read-only session."""
    import psycopg
    from dotenv import load_dotenv
    from psycopg.rows import dict_row

    from api import scorefile

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.read_only = True
        built = scorefile.build(conn, version)
    if built is None:
        raise SystemExit(f"no scores for {version} in the database")
    return built.body


def collect(args, version: str) -> dict[str, bytes]:
    """kind -> uncompressed bytes of every file to publish."""
    files: dict[str, bytes] = {}
    if args.scores:
        files["scores"] = Path(args.scores).read_bytes()
    elif not args.areas_only:
        files["scores"] = build_score_file(version)
    if not args.scores_only:
        areas = Path(args.areas) if args.areas else Path(f"build/static/area-scores.{version}.bin")
        if areas.exists():
            files["areaScores"] = areas.read_bytes()
        elif args.areas or args.areas_only:
            raise SystemExit(f"area scores file not found: {areas}")
        else:
            print(f"no {areas}; area scores not republished", file=sys.stderr)
        if args.tiles:
            files["tiles"] = Path(args.tiles).read_bytes()
    return files


def setup_bucket(s3) -> None:
    s3.put_bucket_cors(Bucket=BUCKET, CORSConfiguration=CORS_RULES)
    print(f"CORS applied to {BUCKET}: {json.dumps(CORS_RULES['CORSRules'][0])}")


def prune(s3, execute: bool) -> None:
    now = datetime.now(timezone.utc)
    objects = []
    for prefix in PREFIXES:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            objects += [(o["Key"], o["LastModified"]) for o in page.get("Contents", [])]
    doomed = prune_candidates(objects, read_manifest(s3), now)
    for key in doomed:
        print(("delete " if execute else "would delete ") + key)
        if execute:
            s3.delete_object(Bucket=BUCKET, Key=key)
    print(f"{len(doomed)} of {len(objects)} objects {'deleted' if execute else 'prunable'}")


def main() -> int:
    from common.config import SCORING_WEIGHTS_VERSION

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--scores", help="a score file to publish instead of building one")
    ap.add_argument("--areas", help="area scores file (default build/static/area-scores.<v>.bin)")
    ap.add_argument("--tiles", help="PMTiles archive, e.g. build/tiles/benrispace.pmtiles")
    ap.add_argument("--scores-only", action="store_true", help="publish only the score file")
    ap.add_argument("--areas-only", action="store_true", help="publish only the area scores")
    ap.add_argument("--weights-version", default=SCORING_WEIGHTS_VERSION)
    ap.add_argument("--setup-bucket", action="store_true", help="apply the CORS rule and exit")
    ap.add_argument("--prune", action="store_true", help="delete unreferenced objects over 7 days")
    ap.add_argument("--yes", action="store_true", help="with --prune: really delete")
    args = ap.parse_args()

    if args.setup_bucket:
        if args.dry_run:
            print(json.dumps(CORS_RULES, indent=2))
        else:
            setup_bucket(client())
        return 0
    if args.prune:
        prune(client(), execute=args.yes and not args.dry_run)
        return 0

    version = args.weights_version
    files = collect(args, version)
    if not files:
        print("nothing to publish", file=sys.stderr)
        return 1
    updates = {kind: entry(kind, version, data) for kind, data in files.items()}
    s3 = client()
    existing = read_manifest(s3)
    manifest = merge_manifest(existing, updates, version, datetime.now(timezone.utc))

    for kind, e in updates.items():
        missing = not exists(s3, e["path"])
        sent, _ = put_args(e["path"], files[kind])
        verb = "upload" if missing else "skip (already there)"
        print(f"{verb:22} {e['path']}  {e['bytes']:,} B raw, {len(sent):,} B on the wire")
        if missing and not args.dry_run:
            body, extra = put_args(e["path"], files[kind])
            s3.put_object(Bucket=BUCKET, Key=e["path"], Body=body, **extra)
    text = json.dumps(manifest, indent=2)
    print(f"manifest.json:\n{text}")
    if not args.dry_run:
        s3.put_object(
            Bucket=BUCKET,
            Key=MANIFEST_KEY,
            Body=text.encode(),
            ContentType="application/json",
            CacheControl=MANIFEST_CACHE,
        )
        print("manifest written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
