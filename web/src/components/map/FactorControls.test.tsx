import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ALL_FACTORS, type FactorSelection } from "@/lib/map/selection";
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
    expect(within(amenities).getAllByRole("checkbox")).toHaveLength(5);
  });

  it("toggles a factor", async () => {
    const user = userEvent.setup();
    const changes: FactorSelection[] = [];
    render(<Harness onChange={(s) => changes.push(s)} />);

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    expect(screen.getByRole("checkbox", { name: /Cafes/ })).not.toBeChecked();
    expect(changes.at(-1)?.factors).not.toContain("cafe");
    expect(screen.getByText(`${FACTOR_KEYS.length - 1} of ${FACTOR_KEYS.length} on`)).toBeInTheDocument();
  });

  it("selects none and all", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Select none" }));
    expect(screen.queryAllByRole("checkbox", { checked: true })).toHaveLength(
      0,
    );
    expect(screen.getByRole("button", { name: "Select none" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getAllByRole("checkbox", { checked: true })).toHaveLength(FACTOR_KEYS.length);
  });

  it("applies a preset and marks it pressed", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Commuter" }));

    expect(screen.getByRole("button", { name: "Commuter" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Family" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(
      screen
        .getAllByRole("checkbox", { checked: true })
        .map((c) => c.closest("label")?.textContent),
    ).toEqual([
      expect.stringContaining("Public transit"),
      expect.stringContaining("Airport access"),
      expect.stringContaining("Road conditions"),
    ]);
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

  it("explains why nothing scores 100 everywhere", () => {
    render(<Harness />);
    expect(
      screen.getByText(/relative within each metro area/),
    ).toBeInTheDocument();
    expect(screen.getByText(/one or two factors/)).toBeInTheDocument();
  });
});
