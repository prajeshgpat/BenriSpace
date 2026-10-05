import { beforeEach, describe, expect, it } from "vitest";

import { emptySubScores } from "@/test/fixtures";

import {
  COMPARE_STORAGE_KEY,
  MAX_COMPARE,
  addPlace,
  bestInRow,
  loadPlaces,
  removePlace,
  savePlaces,
  type ComparePlace,
} from "./compare";

const place = (id: string, score: number, grocery: number | null = null): ComparePlace => ({
  id,
  label: id,
  neighborhood: null,
  score,
  subScores: { ...emptySubScores, grocery },
  lat: 40,
  lon: -73,
});

describe("compare", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("caps at four, ignores duplicates, removes by id", () => {
    let list: ComparePlace[] = [];
    for (let i = 0; i < 6; i++) list = addPlace(list, place(`p${i}`, 50));
    expect(list).toHaveLength(MAX_COMPARE);
    expect(addPlace(list, place("p0", 1))).toHaveLength(MAX_COMPARE);
    expect(removePlace(list, "p1").map((p) => p.id)).toEqual(["p0", "p2", "p3"]);
  });

  it("highlights the best per row, ties included, and skips single values", () => {
    const list = [place("a", 70, 90), place("b", 80, 90), place("c", 60, null)];
    expect([...bestInRow(list, "overall")]).toEqual(["b"]);
    expect([...bestInRow(list, "grocery")].sort()).toEqual(["a", "b"]);
    expect(bestInRow(list, "cafe").size).toBe(0);
    expect(bestInRow([place("a", 70)], "overall").size).toBe(0);
  });

  it("round-trips through sessionStorage and survives junk", () => {
    savePlaces([place("a", 70)]);
    expect(loadPlaces().map((p) => p.id)).toEqual(["a"]);
    window.sessionStorage.setItem(COMPARE_STORAGE_KEY, "{not json");
    expect(loadPlaces()).toEqual([]);
    savePlaces([]);
    expect(window.sessionStorage.getItem(COMPARE_STORAGE_KEY)).toBeNull();
  });
});
