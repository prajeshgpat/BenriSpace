import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FACTOR_GUIDE } from "@/lib/home/factorGuide";
import { FACTOR_KEYS, FACTORS, UNDERLYING_FACTOR_KEYS } from "@/lib/score/factors";
import { EXAMPLE_ADDRESSES } from "@/lib/site";

import { HomePage } from "./HomePage";

describe("HomePage", () => {
  it("has one h1, a main landmark and the footer", () => {
    render(<HomePage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("points the two calls to action at the app and the API", () => {
    render(<HomePage />);
    const open = screen.getAllByRole("link", { name: "Open the app" });
    const api = screen.getAllByRole("link", { name: "See the API" });
    expect(open.length).toBeGreaterThan(0);
    for (const link of open) expect(link).toHaveAttribute("href", "/app");
    for (const link of api) expect(link).toHaveAttribute("href", "/docs");
  });

  it("explains the sections a visitor needs", () => {
    render(<HomePage />);
    for (const name of [
      "How it works",
      "How a score is built",
      "Reading the map",
      "Data sources and limits",
    ]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    expect(screen.getByText("Missing data is left out")).toBeInTheDocument();
  });

  it("describes the twelve factors and the two behind-the-scenes signals with weights", () => {
    render(<HomePage />);
    const cards = screen.getAllByRole("listitem").filter((li) => li.hasAttribute("data-factor"));
    expect(cards).toHaveLength(FACTOR_KEYS.length + UNDERLYING_FACTOR_KEYS.length);
    expect(
      screen.getByRole("heading", { level: 2, name: "Behind-the-scenes signals" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "Running route popularity" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Noise corridor" })).toBeInTheDocument();
    expect(screen.queryByText(/Strava|Emergency corridor|Trail popularity/)).toBeNull();
    for (const key of [...FACTOR_KEYS, ...UNDERLYING_FACTOR_KEYS]) {
      const card = cards.find((li) => li.getAttribute("data-factor") === key)!;
      expect(
        within(card).getByRole("heading", { level: 3, name: FACTORS[key].label }),
      ).toBeInTheDocument();
      expect(card).toHaveTextContent(`Weight: ${FACTOR_GUIDE[key].weight}`);
    }
  });

  it("states the school rule, null policy and that GreatSchools is only linked", () => {
    render(<HomePage />);
    expect(FACTOR_KEYS).toHaveLength(12);
    expect(
      screen.getByRole("heading", { level: 2, name: "The twelve factors" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Schools: 20% proximity, 80% rating"),
    ).toBeInTheDocument();
    expect(screen.getByText(/It is never counted as a zero/)).toBeInTheDocument();
    expect(
      screen.getByText(/GreatSchools is linked, not used as a data source/),
    ).toBeInTheDocument();
  });

  it("links example addresses into the app", () => {
    render(<HomePage />);
    for (const address of EXAMPLE_ADDRESSES) {
      expect(screen.getByRole("link", { name: address })).toHaveAttribute(
        "href",
        `/app?${new URLSearchParams({ address })}`,
      );
    }
  });
});
