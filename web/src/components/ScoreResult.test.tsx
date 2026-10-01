import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";
import { emptySubScores, fullSubScores, makeScore } from "@/test/fixtures";

import { ScoreResult } from "./ScoreResult";

const READY = { status: "ready", text: "Transit is the strongest factor." } as const;

function factorItem(key: string): HTMLElement {
  const item = document.querySelector<HTMLElement>(`[data-factor="${key}"]`);
  if (!item) throw new Error(`No factor row for ${key}`);
  return item;
}

describe("ScoreResult", () => {
  it("leads with the address the user typed, not the API's lat,lon string", () => {
    render(
      <ScoreResult
        address="350 5th Ave, New York, NY"
        score={makeScore()}
        explanation={READY}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "350 5th Ave, New York, NY" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Scored for the area around 40.7492° N, 73.9850° W"),
    ).toBeInTheDocument();
    expect(screen.queryByText("40.74920,-73.98500")).not.toBeInTheDocument();
  });

  it("shows the rounded composite score, its band and the explanation", () => {
    render(<ScoreResult address="x" score={makeScore()} explanation={READY} />);

    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");
    expect(screen.getByText("Good", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Transit is the strongest factor.")).toBeInTheDocument();
  });

  it("renders a row for every factor", () => {
    render(
      <ScoreResult
        address="x"
        score={makeScore({ subScores: fullSubScores })}
        explanation={READY}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(FACTOR_KEYS.length);
    expect(within(factorItem("transit")).getByText("97")).toBeInTheDocument();
    expect(within(factorItem("transit")).getByText("Excellent")).toBeInTheDocument();
    expect(screen.getByText("Based on all 11 factors.")).toBeInTheDocument();
  });

  it("shows null sub-scores as no data with no bar, never as 0", () => {
    render(
      <ScoreResult
        address="x"
        score={makeScore({ subScores: { ...emptySubScores, airport: 62.79 } })}
        explanation={READY}
      />,
    );

    const grocery = factorItem("grocery");
    expect(within(grocery).getByText("No data")).toBeInTheDocument();
    expect(within(grocery).queryByText("0")).not.toBeInTheDocument();
    expect(grocery.querySelector(".fill")).toBeNull();
    expect(grocery.querySelector(".trackEmpty")).not.toBeNull();

    expect(screen.getAllByText("No data")).toHaveLength(FACTOR_KEYS.length - 1);
    expect(factorItem("airport").querySelector(".fill")).toHaveStyle({ width: "63%" });
    expect(screen.getByText(/^Based on 1 of 11 factors\./)).toBeInTheDocument();
  });

  it("shows a real zero as a scored 0, distinct from no data", () => {
    render(
      <ScoreResult
        address="x"
        score={makeScore({ subScores: fullSubScores })}
        explanation={READY}
      />,
    );

    const zero = factorItem("emergencyCorridor");
    expect(within(zero).getByText("0")).toBeInTheDocument();
    expect(within(zero).queryByText("No data")).not.toBeInTheDocument();
    expect(zero.querySelector(".track")).not.toBeNull();
  });

  it("shows weights version and a machine-readable computed date", () => {
    render(<ScoreResult address="x" score={makeScore()} explanation={READY} />);

    expect(screen.getByText("Weights v1-handtuned")).toBeInTheDocument();
    expect(document.querySelector("time")).toHaveAttribute(
      "datetime",
      "2026-09-29T03:12:03.491922Z",
    );
  });

  it("keeps the score visible while the explanation loads or is unavailable", () => {
    const { rerender } = render(
      <ScoreResult address="x" score={makeScore()} explanation={{ status: "loading" }} />,
    );
    expect(screen.getByText("Writing the explanation…")).toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");

    rerender(
      <ScoreResult address="x" score={makeScore()} explanation={{ status: "unavailable" }} />,
    );
    expect(screen.getByText(/explanation isn.t available/)).toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");
  });
});
