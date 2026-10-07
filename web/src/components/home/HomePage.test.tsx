import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { FACTOR_KEYS, FACTORS } from "@/lib/score/factors";

import { HomePage } from "./HomePage";

describe("HomePage", () => {
  it("has one h1, a main landmark and the footer", () => {
    render(<HomePage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("marks the Japanese word as untranslatable Japanese", () => {
    render(<HomePage />);
    const word = screen.getByText("便利");
    expect(word).toHaveAttribute("lang", "ja");
    expect(word).toHaveAttribute("translate", "no");
  });

  it("has a no-JS address search that submits to the app", () => {
    const { container } = render(<HomePage />);
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/app");
    expect(form).toHaveAttribute("method", "get");
    const input = screen.getByRole("combobox", { name: "Address" });
    expect(input).toHaveAttribute("name", "address");
    expect(form).toContainElement(input);
    expect(
      within(form).getByRole("button", { name: "Score" }),
    ).toHaveAttribute("type", "submit");
  });

  it("shows the thirteen factors as icon chips inside three group cards", () => {
    render(<HomePage />);
    expect(FACTOR_KEYS).toHaveLength(13);
    const chips = screen
      .getAllByRole("listitem")
      .filter((li) => li.hasAttribute("data-factor"));
    expect(chips).toHaveLength(13);
    for (const key of FACTOR_KEYS) {
      const chip = chips.find((li) => li.getAttribute("data-factor") === key)!;
      expect(chip).toHaveTextContent(FACTORS[key].label);
      expect(chip.querySelector("svg")).not.toBeNull();
    }
    const section = screen.getByRole("region", { name: "What we score" });
    expect(within(section).getAllByRole("article")).toHaveLength(3);
    for (const name of ["Daily amenities", "Getting around", "Neighborhood"]) {
      expect(
        within(section).getByRole("heading", { level: 3, name }),
      ).toBeInTheDocument();
    }
  });

  it("shows the three steps and mentions feet and miles", () => {
    render(<HomePage />);
    for (const name of ["Search", "See the score", "Make it yours"]) {
      expect(
        screen.getByRole("heading", { level: 3, name }),
      ).toBeInTheDocument();
    }
    expect(screen.getByText(/feet and miles/)).toBeInTheDocument();
  });

  it("has the new hero line and the headline features", () => {
    render(<HomePage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /10-minute radius/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Find your neighborhood.")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "What you get" }),
    ).toBeInTheDocument();
    for (const name of [
      "One score out of 100",
      "Real neighborhoods",
      "Plan several stops",
      "See how far you can get",
      "AI summary",
      "Similar neighborhoods",
      "Improve this area",
    ]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
  });

  it("explains the score, triangulation and optimization with labelled diagrams", () => {
    const { container } = render(<HomePage />);
    expect(
      screen.getByRole("heading", { level: 3, name: "Behind the scenes" }),
    ).toBeInTheDocument();
    const figures = container.querySelectorAll("figure[data-diagram]");
    expect(figures).toHaveLength(3);
    for (const figure of figures) {
      const svg = figure.querySelector("svg")!;
      expect(svg).toHaveAttribute("role", "img");
      expect(svg.getAttribute("aria-label")).toBeTruthy();
      expect(figure.querySelector("figcaption")).not.toBeNull();
    }
    expect(screen.getByText(/real road and rail travel/)).toBeInTheDocument();
    expect(screen.getByText(/lowest total weekly travel/)).toBeInTheDocument();
  });

  it("explains coverage and data", () => {
    render(<HomePage />);
    expect(screen.getByText(/New York, New Jersey and Connecticut/)).toBeInTheDocument();
    expect(screen.getByText(/Built from OpenStreetMap/)).toBeInTheDocument();
  });

  it("offers Ask Benri, carrying typed text without scoring it", async () => {
    render(<HomePage />);
    const ask = screen.getByRole("link", { name: "Ask Benri" });
    expect(ask).toHaveAttribute("href", "/app?chat=1");
    await userEvent.type(
      screen.getByRole("combobox", { name: "Address" }),
      "12 Elm St",
    );
    expect(ask).toHaveAttribute("href", "/app?chat=1&ask=12+Elm+St");
  });

  it("links to the app from the hero and the closing call to action", () => {
    render(<HomePage />);
    expect(
      screen.getByRole("link", { name: "Explore the map" }),
    ).toHaveAttribute("href", "/app");
    expect(
      screen.getByRole("heading", { level: 2, name: "See what's around you" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the app" })).toHaveAttribute(
      "href",
      "/app",
    );
  });
});
