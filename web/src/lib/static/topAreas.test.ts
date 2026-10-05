import { describe, expect, it } from "vitest";

import { FACTOR_KEY_LIST } from "@/lib/api/types";

import type { AreaScores } from "./areaScores";
import { areaComposites, areaKey, localTopAreas } from "./topAreas";

const WIDTH = FACTOR_KEY_LIST.length;

/** Areas with every factor at the given score, spread 1 mile apart along a line. */
function fixture(scores: number[]): AreaScores {
  const count = scores.length;
  const matrix = new Uint8Array(count * WIDTH);
  scores.forEach((score, i) => matrix.fill(score, i * WIDTH, (i + 1) * WIDTH));
  return {
    header: {} as AreaScores["header"],
    count,
    factors: [...FACTOR_KEY_LIST],
    metros: ["New York"],
    names: scores.map((_, i) => `Area ${i}`),
    ids: Uint32Array.from(scores.map((_, i) => 100 + i)),
    lat: Float64Array.from(scores.map((_, i) => 40.7 + i / 69)),
    lon: Float64Array.from(scores.map(() => -73.9)),
    nameIndex: Uint16Array.from(scores.map((_, i) => i)),
    metroIndex: Uint8Array.from(scores.map(() => 0)),
    scores: matrix,
  };
}

describe("localTopAreas", () => {
  it("ranks areas by their own composite and names them from the file", () => {
    const areas = fixture([70, 96, 255, 88]);
    const composites = areaComposites(areas, ["grocery", "transit"], undefined);
    const top = localTopAreas(areas, composites, { limit: 3, minSeparationMi: 0 });
    expect(top.map((r) => r.areaId)).toEqual([101, 103, 100]);
    expect(top[0]).toMatchObject({
      geohash: areaKey(101),
      score: 96,
      neighborhood: "Area 1",
      metroArea: "New York",
    });
  });

  it("spaces results out", () => {
    const areas = fixture([90, 95, 80]);
    const composites = areaComposites(areas, ["grocery"], undefined);
    const top = localTopAreas(areas, composites, { limit: 3, minSeparationMi: 1.5 });
    expect(top.map((r) => r.areaId)).toEqual([101]);
  });
});
