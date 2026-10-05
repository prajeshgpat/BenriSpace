import { FACTOR_KEY_LIST } from "@/lib/api/types";

export interface FixtureArea {
  id: number;
  lat: number;
  lon: number;
  /** Index into `names`, or 65535. */
  name?: number;
  /** Index into `metros`, or 255. */
  metro?: number;
  /** Score per factor in FACTOR_KEY_LIST order (255 = none); missing = 50. */
  scores?: Partial<Record<(typeof FACTOR_KEY_LIST)[number], number>>;
}

export interface FixtureOptions {
  names?: string[];
  metros?: string[];
  headerOverrides?: Record<string, unknown>;
  /** Bytes appended after the last block. */
  trailing?: number;
}

/** Builds an area-score file (format 1) by hand, byte for byte as the contract says. */
export function buildAreaFile(areas: FixtureArea[], options: FixtureOptions = {}): ArrayBuffer {
  const count = areas.length;
  const width = FACTOR_KEY_LIST.length;
  const header = {
    format: 1,
    kind: "areaScores",
    version: "v2.1-handtuned",
    factors: [...FACTOR_KEY_LIST],
    count,
    generatedAt: "2026-01-01T00:00:00Z",
    metros: options.metros ?? ["nyc"],
    names: options.names ?? [],
    ...options.headerOverrides,
  };
  let json = JSON.stringify(header);
  while ((4 + new TextEncoder().encode(json).length) % 4 !== 0) json += " ";
  const headerBytes = new TextEncoder().encode(json);
  const total =
    4 + headerBytes.length + count * (4 + 4 + 4 + 2 + 1 + width) + (options.trailing ?? 0);
  const buffer = new ArrayBuffer(total);
  const view = new DataView(buffer);
  view.setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  const idStart = 4 + headerBytes.length;
  const latStart = idStart + count * 4;
  const lonStart = latStart + count * 4;
  const nameStart = lonStart + count * 4;
  const metroStart = nameStart + count * 2;
  const scoreStart = metroStart + count;
  const bytes = new Uint8Array(buffer);
  areas.forEach((area, i) => {
    view.setUint32(idStart + i * 4, area.id, true);
    view.setInt32(latStart + i * 4, Math.round(area.lat * 1e5), true);
    view.setInt32(lonStart + i * 4, Math.round(area.lon * 1e5), true);
    view.setUint16(nameStart + i * 2, area.name ?? 65535, true);
    bytes[metroStart + i] = area.metro ?? 0;
    FACTOR_KEY_LIST.forEach((key, j) => {
      bytes[scoreStart + i * width + j] = area.scores?.[key] ?? 50;
    });
  });
  return buffer;
}
