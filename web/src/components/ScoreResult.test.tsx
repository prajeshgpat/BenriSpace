import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";
import { emptySubScores, fullSubScores, makeAreaScore, makeScore } from "@/test/fixtures";

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
    expect(screen.getByText("Based on all 12 factors.")).toBeInTheDocument();
  });

  it("puts a decorative icon before each factor label", () => {
    render(
      <ScoreResult
        address="x"
        score={makeScore({ subScores: fullSubScores })}
        explanation={READY}
      />,
    );

    for (const key of FACTOR_KEYS) {
      const svg = factorItem(key).querySelector("svg");
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("data-icon", key);
    }
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
    expect(screen.getByText(/^Based on 1 of 12 factors\./)).toBeInTheDocument();
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

  describe("school detail", () => {
    const GS = "https://www.greatschools.org/school-district-boundaries-map/";

    it("is absent for v1 responses without a school object", () => {
      render(<ScoreResult address="x" score={makeScore()} explanation={READY} />);
      expect(screen.queryByTestId("school-detail")).not.toBeInTheDocument();
      expect(screen.queryByText(/GreatSchools/)).not.toBeInTheDocument();
    });

    it("shows proximity without a fabricated rating when none exists", () => {
      render(
        <ScoreResult
          address="x"
          score={makeScore({
            school: {
              proximity: 72.4,
              ratingAvailable: false,
              districtName: null,
              source: null,
            },
          })}
          explanation={READY}
        />,
      );
      const item = factorItem("school");
      expect(
        within(item).getByText("Proximity 72 · school rating unavailable here"),
      ).toBeInTheDocument();
      expect(within(item).getByText("No data")).toBeInTheDocument();
      const link = within(item).getByRole("link", {
        name: "Explore school ratings on GreatSchools",
      });
      expect(link).toHaveAttribute("href", GS);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer");
    });

    it("shows district and source when a rating exists", () => {
      render(
        <ScoreResult
          address="x"
          score={makeScore({
            subScores: { ...emptySubScores, school: 81 },
            school: {
              proximity: 90,
              ratingAvailable: true,
              districtName: "Great Neck UFSD",
              source: "SEDA",
            },
          })}
          explanation={READY}
        />,
      );
      const item = factorItem("school");
      expect(
        within(item).getByText("Great Neck UFSD · Rating source: SEDA"),
      ).toBeInTheDocument();
      expect(within(item).getByRole("link")).toHaveAttribute("href", GS);
    });
  });

  describe("area result", () => {
    const { area } = makeAreaScore();

    it("labels the area, notes the averaging and keeps the readable address heading", () => {
      render(
        <ScoreResult
          address="14A Rock Street, Jersey City, NJ"
          readableAddress="14A Rock Street, Jersey City, NJ"
          score={makeScore()}
          area={area}
          explanation={READY}
        />,
      );

      expect(
        screen.getByRole("heading", { level: 2, name: "14A Rock Street, Jersey City, NJ" }),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Area bounded by Broadway, Canal St, Bowery and Houston St"),
      ).toBeInTheDocument();
      expect(screen.getByTestId("area-note")).toHaveTextContent(
        "About 0.35 sq mi. Scores blend 3 grid squares (about 0.6 × 0.4 mi each), so this area's score is an average.",
      );
      expect(screen.getByRole("article")).toHaveAccessibleDescription(
        "Area bounded by Broadway, Canal St, Bowery and Houston St",
      );
      expect(screen.queryByText(/Scored for the area around/)).not.toBeInTheDocument();
      expect(screen.getByText("Factor breakdown")).toBeInTheDocument();
    });

    it("uses the singular for one grid square and acres for a small area", () => {
      render(
        <ScoreResult
          address="x"
          score={makeScore()}
          area={{ ...area, cellCount: 1, areaSqMi: 0.05, boundedBy: ["Main St", "Elm St"] }}
          explanation={READY}
        />,
      );

      expect(screen.getByText("Area bounded by Main St and Elm St")).toBeInTheDocument();
      expect(screen.getByTestId("area-note")).toHaveTextContent(
        "About 32 acres. Scores blend 1 grid square (about 0.6 × 0.4 mi), so this area's score is an average.",
      );
    });

    it("falls back to the usual location line when no roads are named", () => {
      render(
        <ScoreResult
          address="x"
          score={makeScore()}
          area={{ ...area, boundedBy: [] }}
          explanation={READY}
        />,
      );
      expect(screen.getByText(/Scored for the area around/)).toBeInTheDocument();
    });

    it("shows no area text for a plain grid-square score", () => {
      render(<ScoreResult address="x" score={makeScore()} explanation={READY} />);
      expect(screen.queryByTestId("area-note")).not.toBeInTheDocument();
    });
  });
});
