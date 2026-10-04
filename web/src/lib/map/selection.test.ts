import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";

import {
  ALL_FACTORS,
  PRESETS,
  activePresetId,
  applyPreset,
  createSelection,
  hasNoFactors,
  importanceOf,
  isAllSelected,
  learnDefaults,
  priorityKey,
  priorityQuery,
  resolveWeights,
  setImportance,
  toggleFactor,
} from "./selection";

describe("selection", () => {
  it("keeps factors in canonical order whatever order they were added", () => {
    expect(createSelection(["transit", "grocery"]).factors).toEqual([
      "grocery",
      "transit",
    ]);
    expect(
      toggleFactor(createSelection(["transit"]), "grocery").factors,
    ).toEqual(["grocery", "transit"]);
  });

  it("toggles a factor off and drops its importance", () => {
    const selection = createSelection(["grocery", "transit"], {
      transit: "high",
    });
    const next = toggleFactor(selection, "transit");
    expect(next.factors).toEqual(["grocery"]);
    expect(next.importance).toEqual({});
  });

  it("sets and clears importance", () => {
    const selection = setImportance(ALL_FACTORS, "cafe", "high");
    expect(importanceOf(selection, "cafe")).toBe("high");
    expect(
      importanceOf(setImportance(selection, "cafe", "normal"), "cafe"),
    ).toBe("normal");
    expect(setImportance(selection, "cafe", "normal").importance).toEqual({});
  });

  it("only offers presets made of real factors", () => {
    for (const preset of PRESETS) {
      expect(preset.factors.length).toBeGreaterThan(0);
      for (const key of preset.factors) expect(FACTOR_KEYS).toContain(key);
    }
  });

  it("uses the v1.4 keys in the presets", () => {
    const byId = Object.fromEntries(PRESETS.map((p) => [p.id, p.factors]));
    expect(byId.errands).toEqual(
      expect.arrayContaining(["grocery", "restaurant", "cafe", "gym", "shopping", "transit"]),
    );
    expect(byId.family).toEqual(
      expect.arrayContaining(["school", "grocery", "recreation", "emergencyCorridor"]),
    );
    expect(byId.commuter).toEqual(
      expect.arrayContaining(["transit", "airport", "gasConvenience", "traffic"]),
    );
  });

  it("weights the Quiet preset on noise corridor and traffic, not gas & convenience", () => {
    const quiet = PRESETS.find((p) => p.id === "quiet")!;
    expect([...quiet.factors].sort()).toEqual(["emergencyCorridor", "traffic"]);
    expect(quiet.factors).not.toContain("gasConvenience");
  });

  it("treats all toggleable factors as 'all selected'", () => {
    expect(isAllSelected(ALL_FACTORS)).toBe(true);
    expect(ALL_FACTORS.factors).toHaveLength(13);
    expect(isAllSelected(toggleFactor(ALL_FACTORS, "bar"))).toBe(false);
  });

  it("recognises the active preset only while importance is untouched", () => {
    const [first] = PRESETS;
    const selection = applyPreset(first);
    expect(activePresetId(selection)).toBe(first.id);
    expect(
      activePresetId(setImportance(selection, first.factors[0], "high")),
    ).toBeNull();
    expect(activePresetId(ALL_FACTORS)).toBeNull();
  });
});

describe("resolveWeights", () => {
  const defaults = { grocery: 1.5, transit: 1.5, cafe: 1 };

  it("returns undefined when nothing differs from the defaults", () => {
    expect(
      resolveWeights(createSelection(["grocery"]), defaults),
    ).toBeUndefined();
  });

  it("scales the learned default by the importance multiplier", () => {
    const selection = createSelection(["grocery", "transit", "cafe"], {
      transit: "high",
      cafe: "low",
    });
    expect(resolveWeights(selection, defaults)).toEqual({
      transit: 3,
      cafe: 0.5,
    });
  });

  it("skips a factor whose default is not known yet", () => {
    const selection = createSelection(["gym"], { gym: "high" });
    expect(resolveWeights(selection, defaults)).toBeUndefined();
  });

  it("never sends weights for factors that are off", () => {
    const selection = createSelection(["grocery"], { transit: "high" });
    expect(resolveWeights(selection, defaults)).toBeUndefined();
  });
});

describe("learnDefaults", () => {
  it("records weights from a response with no overrides", () => {
    expect(
      learnDefaults({}, { grocery: 1.5, transit: 1.5 }, undefined),
    ).toEqual({
      grocery: 1.5,
      transit: 1.5,
    });
  });

  it("does not learn a factor that the request overrode", () => {
    expect(
      learnDefaults({}, { grocery: 1.5, transit: 3 }, { transit: 3 }),
    ).toEqual({ grocery: 1.5 });
  });

  it("returns the same object when nothing is new", () => {
    const known = { grocery: 1.5 };
    expect(learnDefaults(known, { grocery: 1.5 }, undefined)).toBe(known);
  });

  it("ignores unknown keys and non-positive weights", () => {
    expect(learnDefaults({}, { bogus: 1, gym: 0 }, undefined)).toEqual({});
  });
});

describe("priorityQuery", () => {
  it("omits factors when all are selected and keeps them otherwise", () => {
    expect(priorityQuery(ALL_FACTORS, undefined).factors).toBeUndefined();
    const some = createSelection(["transit", "cafe"]);
    expect(priorityQuery(some, { transit: 2 })).toEqual({
      factors: some.factors,
      weights: { transit: 2 },
    });
  });

  it("keys equal queries equally and flags an empty selection", () => {
    expect(priorityKey({})).toBe(priorityKey({ factors: undefined, weights: undefined }));
    expect(priorityKey({ factors: ["cafe"] })).not.toBe(priorityKey({}));
    expect(priorityKey({ weights: { cafe: 1, grocery: 2 } })).toBe(
      priorityKey({ weights: { grocery: 2, cafe: 1 } }),
    );
    expect(hasNoFactors({ factors: [] })).toBe(true);
    expect(hasNoFactors({})).toBe(false);
  });
});
