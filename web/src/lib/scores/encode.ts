import { NULL_SCORE } from "./matrix";

/** Builds a score file the way api/scorefile.py does. For tests and E2E mocks only. */
export function encodeScoreFile(
  factors: readonly string[],
  rows: readonly { geohash: string; scores: readonly (number | null)[] }[],
  version = "test",
): ArrayBuffer {
  const sorted = [...rows].sort((a, b) => (a.geohash < b.geohash ? -1 : 1));
  const header = new TextEncoder().encode(
    JSON.stringify({
      format: 1,
      version,
      factors,
      count: sorted.length,
      geohashLength: 6,
      generatedAt: "2026-10-01T00:00:00+00:00",
    }),
  );
  const out = new Uint8Array(
    4 + header.length + sorted.length * 6 + sorted.length * factors.length,
  );
  new DataView(out.buffer).setUint32(0, header.length, true);
  out.set(header, 4);
  let at = 4 + header.length;
  const ascii = new TextEncoder();
  for (const r of sorted) {
    out.set(ascii.encode(r.geohash), at);
    at += 6;
  }
  for (const r of sorted) {
    for (const v of r.scores) out[at++] = v === null ? NULL_SCORE : v;
  }
  return out.buffer;
}
