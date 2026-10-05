import { describe, expect, it } from "vitest";

import {
  areaMetro,
  areaName,
  areaSubScores,
  decodeAreaScores,
  findAreaIndex,
} from "./areaScores";
import { buildAreaFile } from "./testing";

const SIX = [3, 7, 20, 21, 500, 90000].map((id, i) => ({
  id,
  lat: 40.7 + i * 0.01,
  lon: -74 - i * 0.01,
  name: i % 2 === 0 ? 0 : 65535,
  metro: i === 5 ? 255 : 0,
  scores: { grocery: i * 10, gym: i === 2 ? 255 : 80 },
}));

describe("decodeAreaScores", () => {
  it("decodes every block, including after unaligned ones (N = 6 puts the scores at an odd offset)", () => {
    const areas = decodeAreaScores(
      buildAreaFile(SIX, { names: ["Park Slope, Brooklyn"], metros: ["nyc"] }),
    );
    expect(areas.count).toBe(6);
    expect(Array.from(areas.ids)).toEqual([3, 7, 20, 21, 500, 90000]);
    expect(areas.lat[1]).toBeCloseTo(40.71, 5);
    expect(areas.lon[1]).toBeCloseTo(-74.01, 5);
    expect(areaName(areas, 0)).toBe("Park Slope, Brooklyn");
    expect(areaName(areas, 1)).toBeNull();
    expect(areaMetro(areas, 0)).toBe("nyc");
    expect(areaMetro(areas, 5)).toBeNull();
    const sub = areaSubScores(areas, 3);
    expect(sub.grocery).toBe(30);
    expect(sub.gym).toBe(80);
    expect(sub.cafe).toBe(50);
    expect(areaSubScores(areas, 2).gym).toBeNull();
  });

  it("ignores trailing padding and header padding", () => {
    const areas = decodeAreaScores(buildAreaFile(SIX, { names: ["x"], trailing: 7 }));
    expect(areas.count).toBe(6);
    expect(areas.scores.length).toBe(6 * 13);
  });

  it("decodes an empty file", () => {
    const areas = decodeAreaScores(buildAreaFile([]));
    expect(areas.count).toBe(0);
    expect(findAreaIndex(areas, 1)).toBe(-1);
  });

  it("rejects malformed files", () => {
    const good = buildAreaFile(SIX, { names: ["x"] });
    expect(() => decodeAreaScores(new ArrayBuffer(2))).toThrow();
    expect(() => decodeAreaScores(good.slice(0, 10))).toThrow(/truncated/);
    expect(() => decodeAreaScores(good.slice(0, good.byteLength - 1))).toThrow(/truncated/);
    expect(() => decodeAreaScores(buildAreaFile(SIX, { headerOverrides: { format: 2 } }))).toThrow();
    expect(() =>
      decodeAreaScores(buildAreaFile(SIX, { headerOverrides: { kind: "scores" } })),
    ).toThrow();
    expect(() =>
      decodeAreaScores(buildAreaFile(SIX, { headerOverrides: { factors: ["nope"] } })),
    ).toThrow();
    expect(() => decodeAreaScores(buildAreaFile(SIX, { headerOverrides: { count: -1 } }))).toThrow();
    // Name index beyond the names list.
    expect(() => decodeAreaScores(buildAreaFile(SIX, { names: [] }))).toThrow(/name index/);
    // Metro index beyond the metros list.
    expect(() =>
      decodeAreaScores(buildAreaFile([{ id: 1, lat: 40, lon: -74, metro: 3 }])),
    ).toThrow(/metro index/);
    // Ids out of order.
    expect(() =>
      decodeAreaScores(
        buildAreaFile([
          { id: 5, lat: 40, lon: -74 },
          { id: 4, lat: 40, lon: -74 },
        ]),
      ),
    ).toThrow(/ascending/);
    // Header length larger than the file.
    const bad = good.slice(0);
    new DataView(bad).setUint32(0, 1e6, true);
    expect(() => decodeAreaScores(bad)).toThrow(/header/);
    // Header that is not JSON.
    const junk = good.slice(0);
    new Uint8Array(junk, 4, 4).set([0x7b, 0x7b, 0x7b, 0x7b]);
    expect(() => decodeAreaScores(junk)).toThrow();
  });
});

describe("findAreaIndex", () => {
  const areas = decodeAreaScores(buildAreaFile(SIX, { names: ["x"] }));
  it("finds every id and misses the rest", () => {
    SIX.forEach((area, i) => expect(findAreaIndex(areas, area.id)).toBe(i));
    for (const missing of [0, 4, 22, 499, 90001]) {
      expect(findAreaIndex(areas, missing)).toBe(-1);
    }
  });
});
