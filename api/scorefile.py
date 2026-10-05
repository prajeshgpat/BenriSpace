"""GET /v1/map/scores: every cell's 13 sub-scores in one compact binary file.

The web app downloads it once per weights version and recomputes the overall
score locally for any filter or importance change, so the map recolours with no
API call. Format (all integers little-endian), documented in docs/api.md:

    uint32   header_length
    bytes    header JSON (UTF-8): {"format": 1, "version", "factors": [13 keys],
             "count": N, "geohashLength": 6, "generatedAt": ISO 8601}
    N * 6    geohashes, fixed 6-character ASCII, sorted ascending
    N * 13   uint8 sub-scores, cell-major (cell i, factor j at i * 13 + j);
             0-100 rounded half up, 255 = no score

Built from one SQL query and cached in-process keyed by the ETag.
"""

import gzip
import json
import struct
from dataclasses import dataclass
from datetime import datetime

from api.factors import FACTOR_COLUMNS
from scoring.engine import LEGACY_FALLBACK_COLUMNS

FORMAT_VERSION = 1
GEOHASH_LENGTH = 6
NULL_BYTE = 255
FACTOR_KEYS: tuple[str, ...] = tuple(FACTOR_COLUMNS)


def _select(column: str) -> str:
    legacy = LEGACY_FALLBACK_COLUMNS.get(column)
    expr = f"coalesce(s.{column}, s.{legacy})" if legacy else f"s.{column}"
    return f"{expr} as {column}"


SCORES_SQL = (
    "select ge.geohash, "
    + ", ".join(_select(c) for c in FACTOR_COLUMNS.values())
    + " from scores s join geo_entities ge on ge.id = s.geo_entity_id "
    "where s.weights_version = %s and length(ge.geohash) = " + str(GEOHASH_LENGTH)
)
STAMP_SQL = "select max(computed_at) as stamp from scores where weights_version = %s"


@dataclass(frozen=True)
class ScoreFile:
    etag: str
    body: bytes
    gzipped: bytes


_cache: dict[str, ScoreFile] = {}


def make_etag(version: str, stamp: datetime | None) -> str:
    when = int(stamp.timestamp()) if stamp else 0
    return f'"{version}-{when}"'


def quantize(value) -> int:
    if value is None:
        return NULL_BYTE
    return max(0, min(100, int(float(value) + 0.5)))


def encode(rows: list[dict], version: str, stamp: datetime | None) -> bytes:
    """The binary body for rows of {geohash, <13 score columns>}."""
    rows = sorted(rows, key=lambda r: r["geohash"])
    header = json.dumps(
        {
            "format": FORMAT_VERSION,
            "version": version,
            "factors": list(FACTOR_KEYS),
            "count": len(rows),
            "geohashLength": GEOHASH_LENGTH,
            "generatedAt": stamp.isoformat() if stamp else None,
        },
        separators=(",", ":"),
    ).encode()
    columns = list(FACTOR_COLUMNS.values())
    matrix = bytearray()
    for r in rows:
        matrix.extend(quantize(r[c]) for c in columns)
    hashes = "".join(r["geohash"] for r in rows).encode("ascii")
    return struct.pack("<I", len(header)) + header + hashes + bytes(matrix)


def current_stamp(conn, version: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(STAMP_SQL, (version,))
        row = cur.fetchone()
    return row["stamp"] if row else None


def build(conn, version: str, stamp: datetime | None = None) -> ScoreFile | None:
    """The cached file for `version`, built on a miss; None when it has no scores."""
    stamp = stamp or current_stamp(conn, version)
    if stamp is None:
        return None
    etag = make_etag(version, stamp)
    hit = _cache.get(etag)
    if hit is not None:
        return hit
    with conn.cursor() as cur:
        cur.execute(SCORES_SQL, (version,))
        rows = list(cur)
    if not rows:
        return None
    body = encode(rows, version, stamp)
    built = ScoreFile(etag, body, gzip.compress(body, compresslevel=6, mtime=0))
    _cache.clear()  # one weights version is served at a time
    _cache[etag] = built
    return built
