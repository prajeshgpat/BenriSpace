import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AreaDetails } from "./AreaDetails";

const ROWS = [
  { key: "a", label: "Alpha", value: 40 },
  { key: "b", label: "Bravo", value: 95 },
  { key: "c", label: "Charlie", value: null },
  { key: "d", label: "Delta", value: 70 },
];

describe("AreaDetails", () => {
  it("shows the rounded score, every row and a link to the full result", () => {
    render(
      <AreaDetails
        score={87.6}
        basis="4 selected factors"
        rows={ROWS}
        lat={40.7}
        lon={-74}
      />,
    );

    expect(screen.getByText("88")).toBeInTheDocument();
    expect(screen.getByText("Charlie").nextSibling).toHaveTextContent(
      "No data",
    );
    expect(
      screen.getByRole("link", { name: "Full breakdown" }),
    ).toHaveAttribute("href", "/?lat=40.7&lon=-74");
  });

  it("caps long breakdowns to the strongest rows and says so", () => {
    render(
      <AreaDetails
        score={80}
        basis="4"
        rows={ROWS}
        maxRows={2}
        lat={1}
        lon={2}
      />,
    );

    const labels = screen
      .getAllByRole("listitem")
      .map((li) => li.firstChild?.textContent);
    expect(labels).toEqual(["Bravo", "Delta"]);
    expect(screen.getByText("Top 2 of 4 factors shown.")).toBeInTheDocument();
  });
});
