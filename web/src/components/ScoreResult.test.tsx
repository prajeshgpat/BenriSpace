import { scorePillColor } from "@/lib/score/pillColors";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { emptySubScores, makeAreaScore, makeScore } from "@/test/fixtures";

import { ScoreHeader, ScoreSummary } from "./ScoreResult";

const READY = {
  status: "ready",
  text: "Transit is the strongest factor.",
  explanationSource: "rules",
} as const;

function Summary({
  explanation = READY,
  score = makeScore(),
}: {
  explanation?: Parameters<typeof ScoreSummary>[0]["explanation"];
  score?: ReturnType<typeof makeScore>;
}) {
  return <ScoreSummary score={score} explanation={explanation} />;
}

describe("ScoreHeader", () => {
  it("leads with the address the user typed, not the API's lat,lon string", () => {
    render(<ScoreHeader address="350 5th Ave, New York, NY" score={makeScore()} />);

    expect(
      screen.getByRole("heading", { level: 2, name: "350 5th Ave, New York, NY" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Scored for the area around 40.7492\u00b0 N, 73.9850\u00b0 W"),
    ).toBeInTheDocument();
    expect(screen.queryByText("40.74920,-73.98500")).not.toBeInTheDocument();
  });

  it("shows the rounded composite score and its band, and nothing else", () => {
    render(<ScoreHeader address="x" score={makeScore()} />);

    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");
    expect(
      screen.getByTestId("composite-score").closest("div")!.querySelector("circle[stroke-dasharray]"),
    ).toHaveAttribute("stroke", scorePillColor(63));
    expect(screen.getByText(/Good/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
    expect(screen.queryByText("Factor breakdown")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Weights/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Based on .* factors/)).not.toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  describe("area result", () => {
    const { area } = makeAreaScore();

    it("labels the area and keeps the readable address heading, without size or averaging text", () => {
      render(
        <ScoreHeader
          address="14A Rock Street, Jersey City, NJ"
          readableAddress="14A Rock Street, Jersey City, NJ"
          score={makeScore()}
          area={area}
        />,
      );

      expect(
        screen.getByRole("heading", { level: 2, name: "14A Rock Street, Jersey City, NJ" }),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Area bounded by Broadway, Canal St, Bowery and Houston St"),
      ).toBeInTheDocument();
      expect(screen.getByRole("article")).toHaveAccessibleDescription(
        "Area bounded by Broadway, Canal St, Bowery and Houston St",
      );
      expect(screen.queryByText(/Scored for the area around/)).not.toBeInTheDocument();
      expect(screen.queryByText(/About \d/)).not.toBeInTheDocument();
      expect(screen.queryByText(/grid square/)).not.toBeInTheDocument();
      expect(screen.queryByTestId("area-note")).not.toBeInTheDocument();
    });

    it("falls back to the usual location line when no roads are named", () => {
      render(<ScoreHeader address="x" score={makeScore()} area={{ ...area, boundedBy: [] }} />);
      expect(screen.getByText(/Scored for the area around/)).toBeInTheDocument();
    });

    it("explains the average in a tooltip on the score only for areas", () => {
      const { container, rerender } = render(
        <ScoreHeader address="x" score={makeScore()} area={area} />,
      );
      expect(container.querySelector("[title]:has([data-testid=composite-score])")).toHaveAttribute(
        "title",
        "Average of the cells in this area",
      );
      rerender(<ScoreHeader address="x" score={makeScore()} />);
      expect(container.querySelector("[title]:has([data-testid=composite-score])")).toBeNull();
    });
  });
});

describe("ScoreSummary", () => {
  it("shows the explanation under a Summary heading", () => {
    render(<Summary />);
    expect(screen.getByRole("heading", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getByText("Transit is the strongest factor.")).toBeInTheDocument();
  });

  it("shows loading and unavailable states", () => {
    const { rerender } = render(<Summary explanation={{ status: "loading" }} />);
    expect(screen.getByText("Writing the explanation\u2026")).toBeInTheDocument();
    rerender(<Summary explanation={{ status: "unavailable" }} />);
    expect(screen.getByText(/explanation isn.t available/)).toBeInTheDocument();
  });

  it("captions AI-written text only", () => {
    const { rerender } = render(<Summary />);
    expect(screen.queryByText("AI-written summary")).not.toBeInTheDocument();

    rerender(<Summary explanation={{ ...READY, explanationSource: "ai" }} />);
    expect(screen.getByText("AI-written summary")).toBeInTheDocument();
    expect(screen.getByTestId("ai-caption")).toHaveAttribute(
      "title",
      expect.stringContaining("may be imperfect"),
    );
  });

  describe("school detail", () => {
    const GS = "https://www.greatschools.org/school-district-boundaries-map/";

    it("is absent for v1 responses without a school object", () => {
      render(<Summary />);
      expect(screen.queryByTestId("school-detail")).not.toBeInTheDocument();
    });

    it("shows proximity without a fabricated rating when none exists", () => {
      render(
        <Summary
          score={makeScore({
            school: { proximity: 72.4, ratingAvailable: false, districtName: null, source: null },
          })}
        />,
      );
      expect(
        screen.getByText("Proximity 72 \u00b7 school rating unavailable here"),
      ).toBeInTheDocument();
      const link = screen.getByRole("link", { name: "Explore school ratings on GreatSchools" });
      expect(link).toHaveAttribute("href", GS);
      expect(link).toHaveAttribute("rel", "noreferrer");
    });

    it("shows district and source when a rating exists", () => {
      render(
        <Summary
          score={makeScore({
            subScores: { ...emptySubScores, school: 81 },
            school: { proximity: 90, ratingAvailable: true, districtName: "Great Neck UFSD", source: "SEDA" },
          })}
        />,
      );
      expect(screen.getByText("Great Neck UFSD \u00b7 Rating source: SEDA")).toBeInTheDocument();
    });
  });
});

describe("ScoreSummary while the explanation refreshes", () => {
  it("keeps the text and shows an Updating state", () => {
    render(
      <ScoreSummary
        score={makeScore()}
        explanation={{ status: "ready", text: "Old text.", explanationSource: "ai", updating: true }}
      />,
    );
    expect(screen.getByText("Old text.")).toBeInTheDocument();
    expect(screen.getByTestId("explanation-updating")).toHaveTextContent("Updating…");
  });
});
