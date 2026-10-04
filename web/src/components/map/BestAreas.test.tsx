import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import type { MapTopResult } from "@/lib/api/types";
import { emptySubScores } from "@/test/fixtures";

import { BestAreas } from "./BestAreas";

const RESULTS: MapTopResult[] = [
  {
    geohash: "dr5ru7",
    latitude: 40.7546,
    longitude: -73.985,
    score: 99.8,
    metroArea: "nyc",
    subScores: { ...emptySubScores, grocery: 98, transit: 95, cafe: 60 },
  },
  {
    geohash: "dr5rxn",
    latitude: 40.7276,
    longitude: -73.864,
    score: 91.2,
    metroArea: "nyc",
    subScores: { ...emptySubScores, grocery: 70, transit: 90, cafe: 99 },
  },
];

function renderList(
  props: Partial<React.ComponentProps<typeof BestAreas>> = {},
) {
  const onSelect = vi.fn();
  const onRetry = vi.fn();
  render(
    <BestAreas
      status="ready"
      results={RESULTS}
      error={null}
      selectedFactors={["grocery", "transit"]}
      activeGeohash={null}
      onSelect={onSelect}
      onRetry={onRetry}
      {...props}
    />,
  );
  return { onSelect, onRetry };
}

describe("BestAreas", () => {
  it("lists areas in rank order with score and the strongest selected factors", () => {
    renderList();

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Rank 1");
    expect(items[0]).toHaveTextContent("Unnamed area");
    expect(items[0]).toHaveTextContent("New York");
    expect(items[0]).toHaveTextContent(
      "Strongest: Groceries 98, Public transit 95",
    );
    expect(items[0]).toHaveTextContent("100 out of 100");
  });

  it("never mentions a strong factor the user did not select", () => {
    renderList();
    expect(screen.getAllByRole("listitem")[1]).not.toHaveTextContent("Cafes");
  });

  it("is operable by keyboard and reports the pressed state", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderList();

    await user.tab();
    const [first] = screen.getAllByRole("button", { name: /Rank 1/ });
    expect(first).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith(RESULTS[0]);
    expect(first).toHaveAttribute("aria-pressed", "false");
  });

  it("marks the active area as pressed", () => {
    renderList({ activeGeohash: "dr5ru7" });

    expect(screen.getByRole("button", { name: /Rank 1/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /Rank 2/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("has no scope choice: the list always follows the view", () => {
    renderList();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("says so when nothing is selected, without a list", () => {
    renderList({ selectedFactors: [], results: null, status: "idle" });
    expect(screen.getByText(/Select at least one factor/)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("shows a loading message before the first result", () => {
    renderList({ results: null, status: "loading" });
    expect(screen.getByText("Finding the best areas…")).toBeInTheDocument();
  });

  it("shows an empty state for the current view", () => {
    renderList({ results: [] });
    expect(
      screen.getByText(/No scored areas in this view/),
    ).toBeInTheDocument();
  });

  it("shows a rate-limit error with retry", async () => {
    const user = userEvent.setup();
    const { onRetry } = renderList({
      results: null,
      status: "error",
      error: new ApiError("rate-limited", "x", { status: 429 }),
    });

    expect(screen.getByText(/Too many requests/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("keeps the old list visible behind an error", () => {
    renderList({ status: "error", error: new ApiError("network", "x") });
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/Can't reach BenriSpace/)).toBeInTheDocument();
  });

  it("marks the list busy while it refreshes", () => {
    renderList({ status: "loading" });
    expect(screen.getByRole("list")).toHaveAttribute("aria-busy", "true");
  });

  it("titles rows by neighborhood and never by coordinates", () => {
    renderList({
      results: [
        { ...RESULTS[0], neighborhood: "Park Slope, Brooklyn" },
        RESULTS[1],
      ],
    });
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Park Slope, Brooklyn");
    expect(items[1]).toHaveTextContent("Unnamed area");
    expect(document.body).not.toHaveTextContent(/Area near|40\.7/);
  });

  it("shows the top three rows and reveals the rest behind a Show more button", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 6 }, (_, i) => ({
      ...RESULTS[0],
      geohash: `h${i}`,
      neighborhood: `Place ${i}`,
    }));
    renderList({ results: many });
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    const more = screen.getByRole("button", { name: "Show 3 more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Show fewer" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("reveals a hidden row when its marker is the active one", () => {
    const many = Array.from({ length: 5 }, (_, i) => ({ ...RESULTS[0], geohash: `h${i}` }));
    renderList({ results: many, activeGeohash: "h4" });
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });
});
