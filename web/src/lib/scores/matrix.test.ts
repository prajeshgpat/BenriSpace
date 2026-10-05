import { describe, expect, it } from "vitest";

import { FACTOR_KEY_LIST, type FactorKey } from "@/lib/api/types";

import { encodeScoreFile } from "./encode";
import {
  buildCompositeSpec,
  cellComposite,
  compositeAll,
  decodeScoreMatrix,
  localCells,
  subScoresOf,
} from "./matrix";
import { localTop } from "./topk";

// API order (api/factors.py FACTOR_COLUMNS), which differs from the web's.
const API_ORDER = [
  "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience",
  "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation",
] as const;

// docs/api.md GET /map/top, first real result (gasConvenience is null).
const DOC_ROW = [97.6, 96.7, 99.9, 96.9, 96.5, 62.6, null, 98.4, 89.9, 90.9, 99.7, 95.2, 98.5];

function file(rows: { geohash: string; scores: (number | null)[] }[]) {
  return decodeScoreMatrix(encodeScoreFile(API_ORDER, rows));
}

describe("decodeScoreMatrix", () => {
  it("round-trips hashes, scores and nulls", () => {
    const m = file([
      { geohash: "dr5xsj", scores: DOC_ROW.map((v) => (v === null ? null : Math.round(v))) },
      { geohash: "dr5xsh", scores: DOC_ROW.map(() => 50) },
    ]);
    expect(m.count).toBe(2);
    expect(m.geohashes).toEqual(["dr5xsh", "dr5xsj"]);
    expect(subScoresOf(m, 1).gasConvenience).toBeNull();
    expect(subScoresOf(m, 1).grocery).toBe(98);
    expect(m.lat[0]).toBeGreaterThan(40);
    expect(m.lon[0]).toBeLessThan(-73);
  });

  it("rejects truncated or malformed files", () => {
    const good = encodeScoreFile(API_ORDER, [{ geohash: "dr5xsj", scores: DOC_ROW.map(() => 1) }]);
    expect(() => decodeScoreMatrix(good.slice(0, good.byteLength - 3))).toThrow();
    expect(() => decodeScoreMatrix(new ArrayBuffer(2))).toThrow();
    expect(() => decodeScoreMatrix(new ArrayBuffer(40))).toThrow();
  });
});

describe("composite", () => {
  it("matches the API's composite for the docs/api.md /map/top row", () => {
    const m = file([{ geohash: "dr5xsj", scores: DOC_ROW.map((v) => (v === null ? null : Math.round(v))) }]);
    // api.mapdata.composite_from_row on the unrounded row gives 95.429; the file
    // keeps whole numbers, so the browser is within a fraction of a point.
    expect(cellComposite(m, 0, buildCompositeSpec(m, FACTOR_KEY_LIST, undefined))!).toBeCloseTo(95.429, 0);
    // transit 98 and cafe 100 at weights 14 and 8, and with transit doubled
    const two = buildCompositeSpec(m, ["transit", "cafe"], undefined);
    expect(cellComposite(m, 0, two)).toBeCloseTo((14 * 98 + 8 * 100) / 22, 10);
    const dbl = buildCompositeSpec(m, ["transit", "cafe"], { transit: 28 });
    expect(cellComposite(m, 0, dbl)).toBeCloseTo((28 * 98 + 8 * 100) / 36, 10);
  });

  it("computes the exact weighted average by hand", () => {
    const m = file([{ geohash: "dr5xsj", scores: [100, 0, ...Array(11).fill(null)] }]);
    // grocery 14 x 100, gym 9 x 0 over 23
    const spec = buildCompositeSpec(m, ["grocery", "gym"], undefined);
    expect(cellComposite(m, 0, spec)).toBeCloseTo((14 * 100) / 23, 10);
    // importance: gym doubled to 18
    const heavy = buildCompositeSpec(m, ["grocery", "gym"], { gym: 18 });
    expect(cellComposite(m, 0, heavy)).toBeCloseTo(1400 / 32, 10);
  });

  it("is null when every selected factor is missing, and ignores unselected ones", () => {
    const m = file([{ geohash: "dr5xsj", scores: [null, 80, ...Array(11).fill(null)] }]);
    expect(cellComposite(m, 0, buildCompositeSpec(m, ["grocery"], undefined))).toBeNull();
    expect(cellComposite(m, 0, buildCompositeSpec(m, ["gym"], undefined))).toBe(80);
    expect(Number.isNaN(compositeAll(m, buildCompositeSpec(m, ["grocery"], undefined))[0])).toBe(true);
  });

  it("prefers learned defaults over the built-in ones", () => {
    const m = file([{ geohash: "dr5xsj", scores: [100, 0, ...Array(11).fill(null)] }]);
    const spec = buildCompositeSpec(m, ["grocery", "gym"], undefined, { gym: 1 });
    expect(cellComposite(m, 0, spec)).toBeCloseTo(1400 / 15, 10);
  });
});

describe("localCells", () => {
  const m = file([
    { geohash: "dr5xs1", scores: API_ORDER.map(() => 40) },
    { geohash: "dr5xs2", scores: API_ORDER.map(() => 60) },
    { geohash: "dr5xt1", scores: API_ORDER.map(() => null) },
  ]);
  const all = compositeAll(m, buildCompositeSpec(m, FACTOR_KEY_LIST, undefined));
  const world = [-180, -90, 180, 90] as const;

  it("precision 6 skips cells without a score", () => {
    const cells = localCells(m, world, 6, all);
    expect(cells.geohashes).toEqual(["dr5xs1", "dr5xs2"]);
    expect(cells.scores).toEqual([40, 60]);
  });

  it("precision 5 averages children like the SQL", () => {
    const cells = localCells(m, world, 5, all);
    expect(cells.geohashes).toEqual(["dr5xs"]);
    expect(cells.scores).toEqual([50]);
  });
});

describe("localTop", () => {
  // Three cells in a row ~0.5 mi apart plus one far away.
  const hashes = ["dr5ru0", "dr5ru1", "dr5ru4", "dr72h0"];
  const scores = [90, 85, 80, 70];
  const m = file(hashes.map((geohash, i) => ({ geohash, scores: API_ORDER.map(() => scores[i]) })));
  const all = compositeAll(m, buildCompositeSpec(m, FACTOR_KEY_LIST, undefined));

  it("ranks best first with no spacing", () => {
    const top = localTop(m, all, { limit: 3, minSeparationMi: 0 });
    expect(top.map((r) => r.score)).toEqual([90, 85, 80]);
  });

  it("drops candidates closer than the spacing and keeps ranking order", () => {
    const top = localTop(m, all, { limit: 5, minSeparationMi: 1 });
    expect(top.map((r) => r.geohash)).toEqual(["dr5ru0", "dr72h0"]);
  });

  it("respects the viewport box and marks names as unknown", () => {
    const top = localTop(m, all, { limit: 5, minSeparationMi: 0, bbox: [-74.1, 40.7, -73.9, 40.76] });
    expect(top.every((r) => r.geohash.startsWith("dr5r"))).toBe(true);
    expect(top[0].neighborhood).toBeNull();
  });

  it("matches a brute-force greedy walk on a larger random grid", () => {
    const rows: { geohash: string; scores: number[] }[] = [];
    const chars = "0123456789bcdefghjkmnpqrstuvwxyz";
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (const a of chars) for (const b of chars) {
      rows.push({ geohash: `dr5r${a}${b}`, scores: API_ORDER.map(() => Math.floor(rnd() * 100)) });
    }
    const big = file(rows);
    const comp = compositeAll(big, buildCompositeSpec(big, FACTOR_KEY_LIST, undefined));
    const fast = localTop(big, comp, { limit: 8, minSeparationMi: 1.5 });
    const order = [...big.geohashes.keys()].sort(
      (a, b) => comp[b] - comp[a] || (big.geohashes[a] < big.geohashes[b] ? -1 : 1),
    );
    const kept: number[] = [];
    const dist = (a: number, b: number) => {
      const r = Math.PI / 180;
      const x = (big.lon[a] - big.lon[b]) * r * Math.cos(big.lat[a] * r);
      const y = (big.lat[a] - big.lat[b]) * r;
      return Math.hypot(x, y) * 3958.76;
    };
    for (const i of order) {
      if (kept.length === 8) break;
      if (kept.every((k) => dist(i, k) >= 1.5)) kept.push(i);
    }
    expect(fast.map((r) => r.geohash)).toEqual(kept.map((i) => big.geohashes[i]));
  });
});

it("API order differs from web order, so the decoder must use the header", () => {
  expect([...API_ORDER].sort()).toEqual([...FACTOR_KEY_LIST].sort() as FactorKey[]);
  expect(API_ORDER[1]).not.toBe(FACTOR_KEY_LIST[1]);
});
