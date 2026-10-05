/**
 * The static files on R2 (NEXT_PUBLIC_STATIC_URL). `manifest.json` names the
 * current score file, area-score file and PMTiles archive; every piece is
 * optional, and anything that goes wrong (missing manifest, network, CORS,
 * bad JSON) just means "use the API instead": nothing here throws to callers.
 */

export interface StaticFile {
  /** Relative to the manifest's URL. */
  path: string;
  bytes?: number;
  sha256?: string;
}

export interface StaticManifest {
  weightsVersion?: string;
  generatedAt?: string;
  scores?: StaticFile;
  areaScores?: StaticFile;
  tiles?: StaticFile;
}

const MANIFEST_TIMEOUT_MS = 4000;
const ASSET_TIMEOUT_MS = 30_000;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A file entry with a usable relative path; anything else counts as absent. */
function parseFile(value: unknown): StaticFile | undefined {
  if (!isObject(value) || typeof value.path !== "string") return undefined;
  const path = value.path.trim();
  if (!path || path.startsWith("/") || path.includes("://") || path.includes("..")) {
    return undefined;
  }
  return {
    path,
    bytes: typeof value.bytes === "number" ? value.bytes : undefined,
    sha256: typeof value.sha256 === "string" ? value.sha256 : undefined,
  };
}

/** Throws unless `value` is a format-1 manifest. Unknown fields are ignored. */
export function parseManifest(value: unknown): StaticManifest {
  if (!isObject(value) || value.format !== 1) {
    throw new Error("unsupported static manifest");
  }
  return {
    weightsVersion:
      typeof value.weightsVersion === "string" ? value.weightsVersion : undefined,
    generatedAt: typeof value.generatedAt === "string" ? value.generatedAt : undefined,
    scores: parseFile(value.scores),
    areaScores: parseFile(value.areaScores),
    tiles: parseFile(value.tiles),
  };
}

export function manifestUrl(base: string): string {
  return `${base.replace(/\/+$/, "")}/manifest.json`;
}

/** Absolute URL of a manifest entry; always on the manifest's own origin. */
export function resolveStaticAsset(base: string, file: StaticFile): string {
  const root = manifestUrl(base);
  const url = new URL(file.path, root);
  if (url.origin !== new URL(root).origin) {
    throw new Error("static file is on another origin");
  }
  return url.toString();
}

type FetchLike = typeof fetch;
const manifests = new Map<string, Promise<StaticManifest | null>>();

/**
 * The manifest, fetched once per page (success or failure) and `null` when it
 * cannot be had within a few seconds.
 */
export function loadManifest(
  base: string | undefined,
  fetchImpl: FetchLike = (...args) => fetch(...args),
): Promise<StaticManifest | null> {
  if (!base) return Promise.resolve(null);
  const known = manifests.get(base);
  if (known) return known;
  const loading = (async () => {
    try {
      const response = await fetchImpl(manifestUrl(base), {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(MANIFEST_TIMEOUT_MS),
      });
      if (!response.ok) return null;
      return parseManifest(await response.json());
    } catch {
      return null;
    }
  })();
  manifests.set(base, loading);
  return loading;
}

/** Downloads one manifest file. The browser has already undone Content-Encoding. */
export async function fetchStaticBytes(
  base: string,
  file: StaticFile,
  fetchImpl: FetchLike = (...args) => fetch(...args),
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const timeout = AbortSignal.timeout(ASSET_TIMEOUT_MS);
  const response = await fetchImpl(resolveStaticAsset(base, file), {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  if (!response.ok) throw new Error(`static file failed with ${response.status}`);
  return response.arrayBuffer();
}

const pending = new Map<string, Promise<unknown>>();

/**
 * Loads and decodes one manifest piece, cached per base and piece. Resolves
 * `null` when the static origin is unset, the piece is absent, or anything
 * fails (a failure is remembered for the page: the caller falls back).
 */
export function loadStaticPiece<T>(
  base: string | undefined,
  piece: "scores" | "areaScores",
  decode: (buffer: ArrayBuffer) => T,
  fetchImpl?: FetchLike,
): Promise<T | null> {
  if (!base) return Promise.resolve(null);
  const key = `${base}|${piece}`;
  const known = pending.get(key);
  if (known) return known as Promise<T | null>;
  const loading = (async () => {
    try {
      const manifest = await loadManifest(base, fetchImpl);
      const file = manifest?.[piece];
      if (!file) return null;
      return decode(await fetchStaticBytes(base, file, fetchImpl));
    } catch {
      return null;
    }
  })();
  pending.set(key, loading);
  return loading;
}

/** For tests. */
export function resetStaticCache(): void {
  manifests.clear();
  pending.clear();
}

/** The PMTiles archive URL from the manifest, or `undefined`. */
export async function loadStaticTilesUrl(
  base: string | undefined,
  fetchImpl?: FetchLike,
): Promise<string | undefined> {
  const manifest = await loadManifest(base, fetchImpl);
  if (!base || !manifest?.tiles) return undefined;
  try {
    return resolveStaticAsset(base, manifest.tiles);
  } catch {
    return undefined;
  }
}
