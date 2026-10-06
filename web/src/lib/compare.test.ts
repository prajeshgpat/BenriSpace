import { beforeEach, describe, expect, it } from "vitest";

import { emptySubScores } from "@/test/fixtures";

import {
  COMPARE_STORAGE_KEY,
  MAX_COMPARE,
  addPlace,
  bestInRow,
  biggestDifferences,
  gapFromBest,
  loadPlaces,
  pinWithCurrent,
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

  it("reports gaps from the best and the biggest differences", () => {
    const list = [place("a", 70, 90), place("b", 80, 60), place("c", 60, null)];
    expect(gapFromBest(list, list[0], "overall")).toBe(10);
    expect(gapFromBest(list, list[1], "overall")).toBe(0);
    expect(gapFromBest(list, list[2], "grocery")).toBeNull();
    expect(gapFromBest([list[0]], list[0], "overall")).toBeNull();
    const diffs = biggestDifferences(list);
    expect(diffs).toHaveLength(1);
    expect(diffs[0]).toMatchObject({ row: "grocery", spread: 30, leaderIds: ["a"], trailerIds: ["b"] });
    expect(biggestDifferences([list[0]])).toEqual([]);
  });

  describe("pinWithCurrent", () => {
    const ids = (list: ComparePlace[]) => list.map((p) => p.id);

    it("unpins a place that is already pinned, leaving the current place alone", () => {
      const list = [place("a", 1), place("b", 2)];
      expect(ids(pinWithCurrent(list, place("b", 2), place("c", 3)))).toEqual(["a"]);
    });

    it("pins the current place first, then the new one", () => {
      expect(ids(pinWithCurrent([], place("area", 1), place("here", 2)))).toEqual(["here", "area"]);
      expect(ids(pinWithCurrent([place("x", 1)], place("area", 1), place("here", 2)))).toEqual(["x", "here", "area"]);
    });

    it("pins only the place without a current, for the same place, or when current is pinned", () => {
      expect(ids(pinWithCurrent([], place("area", 1)))).toEqual(["area"]);
      expect(ids(pinWithCurrent([], place("area", 1), null))).toEqual(["area"]);
      expect(ids(pinWithCurrent([], place("area", 1), place("area", 1)))).toEqual(["area"]);
      expect(ids(pinWithCurrent([place("here", 2)], place("area", 1), place("here", 2)))).toEqual(["here", "area"]);
    });

    it("pins only the place when there is no room for both", () => {
      const three = [place("a", 1), place("b", 1), place("c", 1)];
      expect(ids(pinWithCurrent(three, place("area", 1), place("here", 2)))).toEqual(["a", "b", "c", "area"]);
      const full = [...three, place("d", 1)];
      expect(ids(pinWithCurrent(full, place("area", 1), place("here", 2)))).toEqual(["a", "b", "c", "d"]);
    });
  });
});
