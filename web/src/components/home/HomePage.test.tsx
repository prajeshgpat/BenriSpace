import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

  it("has a no-JS address search that submits to the app", () => {
    const { container } = render(<HomePage />);
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/app");
    expect(form).toHaveAttribute("method", "get");
    const input = screen.getByRole("searchbox", { name: "Address" });
    expect(input).toHaveAttribute("name", "address");
    expect(form).toContainElement(input);
    expect(within(form).getByRole("button")).toHaveAttribute("type", "submit");
  });

  it("lists the twelve factors with icons, names and one sentence", () => {
    render(<HomePage />);
    expect(FACTOR_KEYS).toHaveLength(12);
    const items = screen.getAllByRole("listitem").filter((li) => li.hasAttribute("data-factor"));
    expect(items).toHaveLength(12);
    for (const key of FACTOR_KEYS) {
      const item = items.find((li) => li.getAttribute("data-factor") === key)!;
      expect(
        within(item).getByRole("heading", { level: 3, name: FACTORS[key].label }),
      ).toBeInTheDocument();
      expect(item).toHaveTextContent(FACTOR_GUIDE[key].blurb);
      expect(item.querySelector("svg")).not.toBeNull();
    }
    expect(screen.getByRole("heading", { level: 3, name: "Noise corridor" })).toBeInTheDocument();
  });

  it("shows the three steps and mentions feet and miles", () => {
    render(<HomePage />);
    for (const name of ["Search", "See the score", "Understand why"]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
    expect(screen.getByText(/feet and miles/)).toBeInTheDocument();
  });

  it("lists what is coming soon", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 2, name: "Coming soon" })).toBeInTheDocument();
    for (const item of ["AI explanations", "Similar areas", "Compare places"]) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
  });

  it("links to the app from the hero and the closing call to action", () => {
    render(<HomePage />);
    expect(screen.getByRole("link", { name: "Explore the map" })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "Open the app" })).toHaveAttribute("href", "/app");
  });
});
