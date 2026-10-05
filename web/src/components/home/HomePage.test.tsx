import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { FACTOR_GUIDE } from "@/lib/home/factorGuide";
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
      within(form).getByRole("button", { name: "Score it" }),
    ).toHaveAttribute("type", "submit");
  });

  it("lists the thirteen factors with icons, names and one sentence", () => {
    render(<HomePage />);
    expect(FACTOR_KEYS).toHaveLength(13);
    const items = screen
      .getAllByRole("listitem")
      .filter((li) => li.hasAttribute("data-factor"));
    expect(items).toHaveLength(13);
    for (const key of FACTOR_KEYS) {
      const item = items.find((li) => li.getAttribute("data-factor") === key)!;
      expect(
        within(item).getByRole("heading", {
          level: 4,
          name: FACTORS[key].label,
        }),
      ).toBeInTheDocument();
      expect(item).toHaveTextContent(FACTOR_GUIDE[key].blurb);
      expect(item.querySelector("svg")).not.toBeNull();
    }
    expect(
      screen.getByRole("heading", { level: 4, name: "Noise corridor" }),
    ).toBeInTheDocument();
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

  it("states the value proposition and what you get", () => {
    render(<HomePage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /10-minute radius/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "What you get" }),
    ).toBeInTheDocument();
    for (const name of [
      "One score from 13 factors",
      "Real neighborhoods",
      "Improve this area",
      "Similar neighborhoods",
      "Plan multiple stops",
    ]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
  });

  it("groups the factors and explains coverage and data", () => {
    render(<HomePage />);
    for (const name of ["Daily amenities", "Getting around", "Neighborhood"]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
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
    expect(screen.getByRole("link", { name: "Open the app" })).toHaveAttribute(
      "href",
      "/app",
    );
  });
});
