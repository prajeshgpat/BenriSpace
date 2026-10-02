import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MapLegend } from "./MapLegend";

describe("MapLegend", () => {
  it("shows the 0 to 100 ramp and the range actually present", () => {
    render(<MapLegend range={{ min: 31.6, max: 97.2 }} />);

    const legend = screen.getByRole("group", { name: "Score legend" });
    expect(legend).toHaveTextContent("0");
    expect(legend).toHaveTextContent("100");
    expect(legend).toHaveTextContent("In view: 32 to 97");
  });

  it("says so when there is nothing to show", () => {
    render(<MapLegend range={null} />);
    expect(screen.getByText("No scores to show")).toBeInTheDocument();
  });

  it("explains the colors in words for non-visual users", () => {
    render(<MapLegend range={null} />);
    expect(
      screen.getByText(/Darker purple is lower and yellow is higher/),
    ).toBeInTheDocument();
  });
});
