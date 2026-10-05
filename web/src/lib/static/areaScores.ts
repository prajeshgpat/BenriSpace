import { FACTOR_KEY_LIST, type FactorKey, type SubScores } from "@/lib/api/types";
import { NULL_SCORE } from "@/lib/scores/matrix";

/** No neighbourhood name / no metro for an area. */
export const NO_NAME = 65535;
export const NO_METRO = 255;

export interface AreaScoresHeader {
  version: string | number;
  generatedAt: string;
}

/**
 * Every road-bounded area's sub-scores, centre and neighbourhood, decoded from
 * the area-score file (format 1). `scores` is area-major like the cell score
 * file (`i * factors.length + f`, 255 = none), so it works with the same
 * composite helpers (`cellComposite`).
 */
export interface AreaScores {
  header: AreaScoresHeader;
  count: number;
  factors: FactorKey[];
  metros: string[];
  names: string[];
  /** Ascending. */
  ids: Uint32Array;
  lat: Float64Array;
  lon: Float64Array;
  nameIndex: Uint16Array;
  metroIndex: Uint8Array;
  scores: Uint8Array;
}

const FACTOR_SET = new Set<string>(FACTOR_KEY_LIST);

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

/**
 * Throws on anything that is not a well-formed area-score file. The uint16
 * and uint8 blocks leave later blocks unaligned, so every block is copied
 * into its own buffer rather than viewed in place.
 */
export function decodeAreaScores(buffer: ArrayBuffer): AreaScores {
  if (buffer.byteLength < 4) throw new Error("area file too short");
  const view = new DataView(buffer);
  const headerLength = view.getUint32(0, true);
  if (headerLength <= 0 || 4 + headerLength > buffer.byteLength) {
    throw new Error("area file header is truncated");
  }
  const header = JSON.parse(
    new TextDecoder().decode(new Uint8Array(buffer, 4, headerLength)),
  ) as Record<string, unknown>;
  const { factors, count, metros, names } = header;
  if (
    header.format !== 1 ||
    header.kind !== "areaScores" ||
    !Array.isArray(factors) ||
    factors.length === 0 ||
    !factors.every((f) => typeof f === "string" && FACTOR_SET.has(f)) ||
    typeof count !== "number" ||
    !Number.isInteger(count) ||
    count < 0 ||
    !isStringArray(metros) ||
    !isStringArray(names)
  ) {
    throw new Error("area file header is invalid");
  }
  const width = factors.length;
  const idStart = 4 + headerLength;
  const latStart = idStart + count * 4;
  const lonStart = latStart + count * 4;
  const nameStart = lonStart + count * 4;
  const metroStart = nameStart + count * 2;
  const scoreStart = metroStart + count;
  const end = scoreStart + count * width;
  if (buffer.byteLength < end) throw new Error("area file body is truncated");

  const ids = new Uint32Array(count);
  const lat = new Float64Array(count);
  const lon = new Float64Array(count);
  const nameIndex = new Uint16Array(count);
  for (let i = 0; i < count; i++) {
    ids[i] = view.getUint32(idStart + i * 4, true);
    if (i > 0 && ids[i] <= ids[i - 1]) throw new Error("area ids are not ascending");
    lat[i] = view.getInt32(latStart + i * 4, true) / 1e5;
    lon[i] = view.getInt32(lonStart + i * 4, true) / 1e5;
    const name = view.getUint16(nameStart + i * 2, true);
    if (name !== NO_NAME && name >= names.length) throw new Error("area name index out of range");
    nameIndex[i] = name;
  }
  const metroIndex = new Uint8Array(buffer.slice(metroStart, scoreStart));
  for (const m of metroIndex) {
    if (m !== NO_METRO && m >= metros.length) throw new Error("area metro index out of range");
  }
  return {
    header: {
      version: typeof header.version === "string" || typeof header.version === "number" ? header.version : "",
      generatedAt: typeof header.generatedAt === "string" ? header.generatedAt : "",
    },
    count,
    factors: factors as FactorKey[],
    metros,
    names,
    ids,
    lat,
    lon,
    nameIndex,
    metroIndex,
    scores: new Uint8Array(buffer.slice(scoreStart, end)),
  };
}

/** Index of the area with this id, or -1. */
export function findAreaIndex(areas: Pick<AreaScores, "ids" | "count">, id: number): number {
  let low = 0;
  let high = areas.count - 1;
  while (low <= high) {
    const mid = (low + high) >>> 1;
    const value = areas.ids[mid];
    if (value === id) return mid;
    if (value < id) low = mid + 1;
    else high = mid - 1;
  }
  return -1;
}

/** The area's sub-scores keyed like the API's, `null` where it has none. */
export function areaSubScores(areas: AreaScores, index: number): SubScores {
  const width = areas.factors.length;
  return Object.fromEntries(
    FACTOR_KEY_LIST.map((key) => {
      const column = areas.factors.indexOf(key);
      if (column === -1) return [key, null];
      const value = areas.scores[index * width + column];
      return [key, value === NULL_SCORE ? null : value];
    }),
  ) as SubScores;
}

/** The area's neighbourhood, e.g. "Park Slope, Brooklyn", or `null`. */
export function areaName(areas: AreaScores, index: number): string | null {
  const name = areas.nameIndex[index];
  return name === NO_NAME ? null : (areas.names[name] ?? null);
}

export function areaMetro(areas: AreaScores, index: number): string | null {
  const metro = areas.metroIndex[index];
  return metro === NO_METRO ? null : (areas.metros[metro] ?? null);
}
