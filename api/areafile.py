"""Static area-scores file (R2 `areas/<version>.<sha12>.bin`): every road-bounded area's
id, centroid, neighbourhood, metro and 13 sub-scores in one compact binary, so the web app
can search and colour areas without an API call. Format 1, all integers little-endian
(contract in docs/ARCHITECTURE.md, "Static files on R2"):

    uint32   header_length (header is padded with ASCII spaces so 4 + header_length % 4 == 0)
    bytes    header JSON (UTF-8): {"format": 1, "kind": "areaScores", "version", "factors":
             [13 keys], "count": N, "generatedAt", "metros": [...], "names": [...]}
    N * 4    uint32 area ids, ascending
    N * 4    int32 centroid latitude * 1e5 (rounded)
    N * 4    int32 centroid longitude * 1e5
    N * 2    uint16 index into header.names (65535 = none)
    N * 1    uint8 index into header.metros (255 = none)
    N * 13   uint8 sub-scores, area-major, 0-100 rounded half up, 255 = no score

Readers ignore any trailing bytes. Pure functions only; scripts/build_area_scores.py
computes the scores.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

from api.scorefile import FACTOR_KEYS

FORMAT_VERSION = 1
KIND = "areaScores"
NO_NAME = 65535
NO_METRO = 255
COORD_SCALE = 100_000
N_FACTORS = len(FACTOR_KEYS)


@dataclass(frozen=True)
class AreaRow:
    id: int
    lat: float
    lon: float
    name: str | None
    metro: str | None
    scores: tuple[int, ...]  # N_FACTORS bytes, already quantized (255 = none)


def encode(rows: list[AreaRow], version: str, generated_at: str) -> bytes:
    rows = sorted(rows, key=lambda r: r.id)
    metros = sorted({r.metro for r in rows if r.metro})
    names = sorted({r.name for r in rows if r.name})
    if len(names) >= NO_NAME or len(metros) >= NO_METRO:
        raise ValueError("too many distinct names or metros for the index widths")
    name_ix = {n: i for i, n in enumerate(names)}
    metro_ix = {m: i for i, m in enumerate(metros)}
    header = json.dumps(
        {
            "format": FORMAT_VERSION,
            "kind": KIND,
            "version": version,
            "factors": list(FACTOR_KEYS),
            "count": len(rows),
            "generatedAt": generated_at,
            "metros": metros,
            "names": names,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    header += b" " * (-(4 + len(header)) % 4)
    n = len(rows)
    for r in rows:
        if len(r.scores) != N_FACTORS:
            raise ValueError(f"area {r.id}: expected {N_FACTORS} scores")
    body = b"".join(
        [
            struct.pack(f"<{n}I", *(r.id for r in rows)),
            struct.pack(f"<{n}i", *(round(r.lat * COORD_SCALE) for r in rows)),
            struct.pack(f"<{n}i", *(round(r.lon * COORD_SCALE) for r in rows)),
            struct.pack(f"<{n}H", *(name_ix.get(r.name, NO_NAME) for r in rows)),
            struct.pack(f"<{n}B", *(metro_ix.get(r.metro, NO_METRO) for r in rows)),
            bytes(v for r in rows for v in r.scores),
        ]
    )
    return struct.pack("<I", len(header)) + header + body


def decode(data: bytes) -> tuple[dict, list[AreaRow]]:
    (hlen,) = struct.unpack_from("<I", data, 0)
    header = json.loads(data[4 : 4 + hlen].decode())
    if header.get("format") != FORMAT_VERSION or header.get("kind") != KIND:
        raise ValueError("not an areaScores format 1 file")
    n = header["count"]
    f = len(header["factors"])
    off = 4 + hlen
    ids = struct.unpack_from(f"<{n}I", data, off)
    off += 4 * n
    lats = struct.unpack_from(f"<{n}i", data, off)
    off += 4 * n
    lons = struct.unpack_from(f"<{n}i", data, off)
    off += 4 * n
    names = struct.unpack_from(f"<{n}H", data, off)
    off += 2 * n
    metros = struct.unpack_from(f"<{n}B", data, off)
    off += n
    matrix = data[off : off + n * f]
    if len(matrix) != n * f:
        raise ValueError("truncated areaScores file")
    rows = [
        AreaRow(
            ids[i],
            lats[i] / COORD_SCALE,
            lons[i] / COORD_SCALE,
            None if names[i] == NO_NAME else header["names"][names[i]],
            None if metros[i] == NO_METRO else header["metros"][metros[i]],
            tuple(matrix[i * f : (i + 1) * f]),
        )
        for i in range(n)
    ]
    return header, rows
