import { scorePillColor } from "@/lib/score/pillColors";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ALL_FACTORS, createSelection, type FactorSelection } from "@/lib/map/selection";
import { FACTOR_KEYS } from "@/lib/score/factors";

import { FactorControls } from "./FactorControls";

function Harness({
  initial = ALL_FACTORS,
  onChange,
}: {
  initial?: FactorSelection;
  onChange?: (s: FactorSelection) => void;
}) {
  const [selection, setSelection] = useState(initial);
  return (
    <FactorControls
      selection={selection}
      onChange={(next) => {
        setSelection(next);
        onChange?.(next);
      }}
    />
  );
}

describe("FactorControls", () => {
  it("shows a checkbox for each of the toggleable factors, grouped like the score card", () => {
    render(<Harness />);

    expect(screen.getAllByRole("checkbox")).toHaveLength(FACTOR_KEYS.length);
    for (const name of ["Daily amenities", "Getting around", "Neighborhood"]) {
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    }
    const amenities = screen.getByRole("group", { name: "Daily amenities" });
    expect(within(amenities).getAllByRole("checkbox")).toHaveLength(6);
  });

  it("toggles a factor", async () => {
    const user = userEvent.setup();
    const changes: FactorSelection[] = [];
    render(<Harness onChange={(s) => changes.push(s)} />);

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    expect(screen.getByRole("checkbox", { name: /Cafes/ })).not.toBeChecked();
    expect(changes.at(-1)?.factors).not.toContain("cafe");
    expect(screen.queryByText(/ on$/)).not.toBeInTheDocument();
  });

  it("has no count, presets or select all/none", () => {
    render(<Harness />);
    expect(screen.queryByText(/\d+ of \d+ on/)).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Presets" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select all" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select none" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("checkbox", { checked: true })).toHaveLength(FACTOR_KEYS.length);
  });

  it("offers importance only for enabled factors, in a disclosure and records the choice", async () => {
    const user = userEvent.setup();
    const changes: FactorSelection[] = [];
    render(<Harness onChange={(s) => changes.push(s)} />);

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Public transit" }),
      "high",
    );

    expect(changes.at(-1)?.importance).toEqual({ transit: "high" });
    await user.click(screen.getByRole("checkbox", { name: /Public transit/ }));
    expect(
      screen.queryByRole("combobox", { name: "Public transit" }),
    ).not.toBeInTheDocument();
    expect(changes.at(-1)?.importance).toEqual({});
  });
});

describe("factor icons", () => {
  it("shows a decorative icon before every factor label", () => {
    render(<FactorControls selection={ALL_FACTORS} onChange={() => {}} />);
    const toggles = screen.getAllByRole("checkbox");
    expect(toggles.length).toBeGreaterThan(0);
    for (const box of toggles) {
      const label = box.closest("label")!;
      const svg = label.querySelector("svg");
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(label.firstElementChild).toBe(box);
      expect(box.nextElementSibling).toBe(svg);
    }
  });
});

describe("FactorControls score rings", () => {
  const SCORES = { grocery: 97.6, cafe: 12, school: null } as const;

  function renderWith(selection: FactorSelection, scores: typeof SCORES | null) {
    return render(
      <FactorControls selection={selection} onChange={() => {}} scores={scores} />,
    );
  }

  it("shows no rings without a result", () => {
    renderWith(ALL_FACTORS, null);
    expect(screen.queryAllByTestId("factor-ring")).toHaveLength(0);
  });

  it("rings only selected factors, with the number printed and the ring hidden from AT", () => {
    renderWith(createSelection(["grocery", "cafe"]), SCORES);

    const rings = screen.getAllByTestId("factor-ring");
    expect(rings).toHaveLength(2);
    for (const ring of rings) expect(ring).toHaveAttribute("aria-hidden", "true");

    const grocery = screen.getByRole("checkbox", { name: /Groceries/ });
    expect(within(grocery.closest("label")!).getByTestId("factor-ring")).toHaveTextContent("98");
    const arc = grocery.closest("label")!.querySelector("circle[stroke-dasharray]");
    expect(arc).not.toBeNull();
    // Quality ramp (not the map's viridis): near-top scores are blended toward green.
    expect(arc).toHaveAttribute("stroke", scorePillColor(98));
    expect(arc!.getAttribute("stroke")).toContain("--score-100");
    const cafe = screen.getByRole("checkbox", { name: /Cafes/ });
    expect(
      cafe.closest("label")!.querySelector("circle[stroke-dasharray]"),
    ).toHaveAttribute("stroke", scorePillColor(12));

    const bar = screen.getByRole("checkbox", { name: /Bars/ });
    expect(within(bar.closest("label")!).queryByTestId("factor-ring")).toBeNull();
  });

  it("names the score in the toggle's accessible name", () => {
    renderWith(createSelection(["grocery"]), SCORES);
    expect(
      screen.getByRole("checkbox", { name: "Groceries, on, scored 98 out of 100" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Bars" })).toBeInTheDocument();
  });

  it("shows a muted n/a ring for a selected factor with no data", () => {
    renderWith(createSelection(["school", "traffic"]), SCORES);
    const school = screen.getByRole("checkbox", { name: /^Schools, on, no data/ });
    const ring = within(school.closest("label")!).getByTestId("factor-ring");
    expect(ring).toHaveTextContent("n/a");
    expect(ring).toHaveAttribute("data-state", "none");
    expect(ring.querySelector("circle[stroke-dasharray='3 3']")).toBeNull();
    expect(ring.querySelector("[stroke*='--score']")).toBeNull();
    // A factor missing from the map counts as no data too.
    expect(screen.getAllByText("n/a")).toHaveLength(2);
  });
});
