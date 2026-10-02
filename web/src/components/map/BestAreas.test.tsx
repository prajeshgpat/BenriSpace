import { render, screen, within } from "@testing-library/react";
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
  const onScopeChange = vi.fn();
  const onRetry = vi.fn();
  render(
    <BestAreas
      status="ready"
      results={RESULTS}
      error={null}
      selectedFactors={["grocery", "transit"]}
      scope="metro"
      onScopeChange={onScopeChange}
      activeGeohash={null}
      onSelect={onSelect}
      onRetry={onRetry}
      {...props}
    />,
  );
  return { onSelect, onScopeChange, onRetry };
}

describe("BestAreas", () => {
  it("lists areas in rank order with score and the strongest selected factors", () => {
    renderList();

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Rank 1");
    expect(items[0]).toHaveTextContent("Area near 40.755, -73.985");
    expect(items[0]).toHaveTextContent("New York");
    expect(items[0]).toHaveTextContent(
      "Strongest: Grocery stores 98, Public transit 95",
    );
    expect(items[0]).toHaveTextContent("100 out of 100");
  });

  it("never mentions a strong factor the user did not select", () => {
    renderList();
    expect(screen.getAllByRole("listitem")[1]).not.toHaveTextContent("Cafes");
  });

  it("is operable by keyboard and reports the expanded state", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderList();

    // The radio group is a single tab stop, then the first area.
    await user.tab();
    await user.tab();
    const [first] = screen.getAllByRole("button", { name: /Rank 1/ });
    expect(first).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith(RESULTS[0]);
    expect(first).toHaveAttribute("aria-expanded", "false");
  });

  it("shows the breakdown and a full-result link for the active area", () => {
    renderList({ activeGeohash: "dr5ru7" });

    const item = screen.getAllByRole("listitem")[0];
    expect(screen.getByRole("button", { name: /Rank 1/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(item).getByText("Grocery stores")).toBeInTheDocument();
    expect(
      within(item).getByRole("link", { name: "Full breakdown" }),
    ).toHaveAttribute("href", "/?lat=40.7546&lon=-73.985");
  });

  it("switches scope with radios", async () => {
    const user = userEvent.setup();
    const { onScopeChange } = renderList();

    expect(screen.getByRole("radio", { name: "Whole metro" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "This view only" }));

    expect(onScopeChange).toHaveBeenCalledWith("view");
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

  it("shows an empty state that depends on scope", () => {
    renderList({ results: [], scope: "view" });
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
});
