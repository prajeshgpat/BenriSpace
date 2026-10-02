import { describe, expect, it } from "vitest";

import type { Suggestion } from "@/lib/api/types";

import {
  comboboxReducer,
  describeCount,
  initialComboboxState,
  isOpen,
  normalizeQuery,
  optionId,
  type ComboboxAction,
  type ComboboxState,
} from "./combobox";

const A: Suggestion = {
  label: "350 5th Avenue, New York, NY",
  latitude: 40.7484,
  longitude: -73.9857,
};
const B: Suggestion = {
  label: "350 5th Street, Brooklyn, NY",
  latitude: 40.67,
  longitude: -73.98,
};
const C: Suggestion = {
  label: "350 5th Road, Queens, NY",
  latitude: 40.74,
  longitude: -73.84,
};

function run(...actions: ComboboxAction[]): ComboboxState {
  return actions.reduce(comboboxReducer, initialComboboxState);
}

const loaded = (...actions: ComboboxAction[]) =>
  run(
    { type: "typed", text: "350 5th" },
    { type: "received", query: "350 5th", suggestions: [A, B, C] },
    ...actions,
  );

describe("combobox reducer", () => {
  it("normalises whitespace in the query", () => {
    expect(normalizeQuery("  350   5th ")).toBe("350 5th");
  });

  it("stays closed with fewer than 3 characters", () => {
    const state = run({ type: "typed", text: "35" });
    expect(isOpen(state)).toBe(false);
    expect(state.suggestions).toEqual([]);
  });

  it("clears a stale list when the text drops below the minimum", () => {
    const state = loaded({ type: "typed", text: "35" });
    expect(state.suggestions).toEqual([]);
    expect(isOpen(state)).toBe(false);
  });

  it("opens when suggestions arrive for the current text", () => {
    const state = loaded();
    expect(isOpen(state)).toBe(true);
    expect(state.activeIndex).toBe(-1);
  });

  it("ignores a response for text that has since changed", () => {
    const state = run(
      { type: "typed", text: "350 5th" },
      { type: "typed", text: "350 5th av" },
      { type: "received", query: "350 5th", suggestions: [A] },
    );
    expect(state.suggestions).toEqual([]);
  });

  it("ignores a failure for text that has since changed", () => {
    const state = loaded(
      { type: "typed", text: "350 5th av" },
      { type: "failed", query: "350 5th" },
    );
    expect(state.suggestions).toHaveLength(3);
  });

  it("empties the list when the current lookup fails, with no error state", () => {
    const state = loaded({ type: "failed", query: "350 5th" });
    expect(isOpen(state)).toBe(false);
    expect(Object.keys(state)).not.toContain("error");
  });

  it("resets the active option on typing, so Enter submits the typed text", () => {
    const state = loaded(
      { type: "navigate", key: "ArrowDown" },
      { type: "typed", text: "350 5th a" },
    );
    expect(state.activeIndex).toBe(-1);
  });

  describe("keyboard navigation", () => {
    it("ArrowDown moves forward and wraps to the first", () => {
      const downs = (n: number) =>
        loaded(
          ...Array.from(
            { length: n },
            () => ({ type: "navigate", key: "ArrowDown" }) as const,
          ),
        );
      expect(downs(1).activeIndex).toBe(0);
      expect(downs(3).activeIndex).toBe(2);
      expect(downs(4).activeIndex).toBe(0);
    });

    it("ArrowUp from nothing selects the last, then moves back and wraps", () => {
      expect(loaded({ type: "navigate", key: "ArrowUp" }).activeIndex).toBe(2);
      expect(
        loaded(
          { type: "navigate", key: "ArrowDown" },
          { type: "navigate", key: "ArrowUp" },
        ).activeIndex,
      ).toBe(2);
      expect(
        loaded(
          { type: "navigate", key: "End" },
          { type: "navigate", key: "ArrowUp" },
        ).activeIndex,
      ).toBe(1);
    });

    it("Home and End jump to the ends", () => {
      expect(loaded({ type: "navigate", key: "End" }).activeIndex).toBe(2);
      expect(
        loaded(
          { type: "navigate", key: "End" },
          { type: "navigate", key: "Home" },
        ).activeIndex,
      ).toBe(0);
    });

    it("does nothing without suggestions", () => {
      expect(run({ type: "navigate", key: "ArrowDown" })).toBe(
        initialComboboxState,
      );
    });

    it("reopens a dismissed list from the first option", () => {
      const state = loaded({ type: "dismiss" });
      expect(isOpen(state)).toBe(false);
      const reopened = comboboxReducer(state, {
        type: "navigate",
        key: "ArrowDown",
      });
      expect(isOpen(reopened)).toBe(true);
      expect(reopened.activeIndex).toBe(0);
    });
  });

  it("dismiss closes the list and clears the active option", () => {
    const state = loaded(
      { type: "navigate", key: "ArrowDown" },
      { type: "dismiss" },
    );
    expect(isOpen(state)).toBe(false);
    expect(state.activeIndex).toBe(-1);
  });

  it("keeps a dismissed list closed when a response arrives, until the next edit", () => {
    const dismissed = run(
      { type: "typed", text: "350 5th" },
      { type: "dismiss" },
      { type: "received", query: "350 5th", suggestions: [A] },
    );
    expect(isOpen(dismissed)).toBe(false);
    expect(
      isOpen(comboboxReducer(dismissed, { type: "typed", text: "350 5th a" })),
    ).toBe(true);
  });

  it("reset returns to the initial state", () => {
    expect(loaded({ type: "reset" })).toEqual(initialComboboxState);
  });

  it("builds stable option ids and the live-region text", () => {
    expect(optionId("lb", 2)).toBe("lb-option-2");
    expect(describeCount(0)).toBe("");
    expect(describeCount(1)).toBe("1 suggestion available");
    expect(describeCount(5)).toBe("5 suggestions available");
  });
});
