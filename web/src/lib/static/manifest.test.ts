import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchStaticBytes,
  loadManifest,
  loadStaticPiece,
  loadStaticTilesUrl,
  manifestUrl,
  parseManifest,
  resetStaticCache,
  resolveStaticAsset,
} from "./manifest";

const BASE = "https://tiles.example.com";

const MANIFEST = {
  format: 1,
  weightsVersion: "v2.1-handtuned",
  generatedAt: "2026-01-01T00:00:00Z",
  scores: { path: "scores/v2.1-handtuned.abc123.bin", bytes: 4, sha256: "aa" },
  areaScores: { path: "areas/v2.1-handtuned.abc123.bin", bytes: 4, sha256: "bb" },
  tiles: { path: "tiles/benrispace.abc123.pmtiles", bytes: 9, sha256: "cc" },
  future: { anything: true },
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => resetStaticCache());

describe("parseManifest", () => {
  it("reads the three pieces and ignores unknown fields", () => {
    const manifest = parseManifest(MANIFEST);
    expect(manifest.scores?.path).toBe("scores/v2.1-handtuned.abc123.bin");
    expect(manifest.areaScores?.path).toBe("areas/v2.1-handtuned.abc123.bin");
    expect(manifest.tiles?.path).toBe("tiles/benrispace.abc123.pmtiles");
    expect(manifest).not.toHaveProperty("future");
  });

  it("lets any piece be absent", () => {
    const manifest = parseManifest({ format: 1, tiles: MANIFEST.tiles });
    expect(manifest.scores).toBeUndefined();
    expect(manifest.areaScores).toBeUndefined();
    expect(manifest.tiles).toBeDefined();
  });

  it("rejects other formats and non-objects", () => {
    expect(() => parseManifest({ ...MANIFEST, format: 2 })).toThrow();
    expect(() => parseManifest({})).toThrow();
    expect(() => parseManifest(null)).toThrow();
    expect(() => parseManifest([MANIFEST])).toThrow();
  });

  it("drops entries with an unusable path", () => {
    const manifest = parseManifest({
      format: 1,
      scores: { path: "/abs.bin" },
      areaScores: { path: "https://evil.example/x.bin" },
      tiles: { path: "../up.pmtiles" },
    });
    expect(manifest.scores).toBeUndefined();
    expect(manifest.areaScores).toBeUndefined();
    expect(manifest.tiles).toBeUndefined();
  });
});

describe("urls", () => {
  it("resolves paths against the manifest URL", () => {
    expect(manifestUrl(`${BASE}/`)).toBe(`${BASE}/manifest.json`);
    expect(resolveStaticAsset(BASE, { path: "scores/a.bin" })).toBe(`${BASE}/scores/a.bin`);
    expect(resolveStaticAsset(`${BASE}/v1`, { path: "scores/a.bin" })).toBe(
      `${BASE}/v1/scores/a.bin`,
    );
  });
});

describe("loadManifest", () => {
  it("fetches once and shares the promise", async () => {
    const fetchImpl = vi.fn(async () => json(MANIFEST));
    const [a, b] = await Promise.all([
      loadManifest(BASE, fetchImpl),
      loadManifest(BASE, fetchImpl),
    ]);
    expect(a).toBe(b);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledWith(`${BASE}/manifest.json`, expect.anything());
  });

  it("is null with no base, a bad status, a network error or a bad body", async () => {
    expect(await loadManifest(undefined)).toBeNull();
    expect(await loadManifest(BASE, async () => json({}, 404))).toBeNull();
    resetStaticCache();
    expect(
      await loadManifest(BASE, async () => {
        throw new TypeError("CORS");
      }),
    ).toBeNull();
    resetStaticCache();
    expect(await loadManifest(BASE, async () => json({ format: 9 }))).toBeNull();
    resetStaticCache();
    expect(await loadManifest(BASE, async () => new Response("<html>"))).toBeNull();
  });
});

describe("loadStaticPiece", () => {
  const decode = (buffer: ArrayBuffer) => new Uint8Array(buffer).length;

  it("downloads and decodes a piece", async () => {
    const fetchImpl = vi.fn(async (url: RequestInfo | URL) =>
      String(url).endsWith("manifest.json")
        ? json(MANIFEST)
        : new Response(new Uint8Array([1, 2, 3, 4])),
    );
    expect(await loadStaticPiece(BASE, "scores", decode, fetchImpl)).toBe(4);
    expect(fetchImpl).toHaveBeenCalledWith(`${BASE}/scores/v2.1-handtuned.abc123.bin`, expect.anything());
    // Cached: no further requests.
    expect(await loadStaticPiece(BASE, "scores", decode, fetchImpl)).toBe(4);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("is null when the piece is absent, the download fails or decoding throws", async () => {
    const absent = async () => json({ format: 1 });
    expect(await loadStaticPiece(BASE, "scores", decode, absent)).toBeNull();
    resetStaticCache();
    const broken = async (url: RequestInfo | URL) =>
      String(url).endsWith("manifest.json") ? json(MANIFEST) : new Response("no", { status: 500 });
    expect(await loadStaticPiece(BASE, "areaScores", decode, broken)).toBeNull();
    resetStaticCache();
    const bad = async (url: RequestInfo | URL) =>
      String(url).endsWith("manifest.json") ? json(MANIFEST) : new Response(new Uint8Array(1));
    expect(
      await loadStaticPiece(
        BASE,
        "areaScores",
        () => {
          throw new Error("bad file");
        },
        bad,
      ),
    ).toBeNull();
    expect(await loadStaticPiece(undefined, "scores", decode)).toBeNull();
  });
});

describe("loadStaticTilesUrl", () => {
  it("returns the archive URL, or undefined without one", async () => {
    expect(await loadStaticTilesUrl(BASE, async () => json(MANIFEST))).toBe(
      `${BASE}/tiles/benrispace.abc123.pmtiles`,
    );
    resetStaticCache();
    expect(await loadStaticTilesUrl(BASE, async () => json({ format: 1 }))).toBeUndefined();
    expect(await loadStaticTilesUrl(undefined)).toBeUndefined();
  });
});

describe("fetchStaticBytes", () => {
  it("throws on a failed response", async () => {
    await expect(
      fetchStaticBytes(BASE, { path: "x.bin" }, async () => new Response("", { status: 404 })),
    ).rejects.toThrow(/404/);
  });
});
