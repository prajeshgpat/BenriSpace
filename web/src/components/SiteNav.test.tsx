import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SiteNav } from "./SiteNav";

const pathname = vi.hoisted(() => vi.fn(() => "/"));
vi.mock("next/navigation", () => ({ usePathname: pathname }));

describe("SiteNav", () => {
  it("lists every tab in order", () => {
    render(<SiteNav />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Map",
      "For Business",
      "Developers",
      "Pricing",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/app",
      "/business",
      "/docs",
      "/pricing",
    ]);
  });

  it("marks only the current page", () => {
    pathname.mockReturnValue("/pricing");
    render(<SiteNav />);
    expect(screen.getByRole("link", { name: "Pricing" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    for (const name of ["Map", "For Business", "Developers"]) {
      expect(screen.getByRole("link", { name })).not.toHaveAttribute(
        "aria-current",
      );
    }
  });

  it("marks Map on /app", () => {
    pathname.mockReturnValue("/app");
    render(<SiteNav />);
    expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks no tab on the home page, which the logo links", () => {
    pathname.mockReturnValue("/");
    render(<SiteNav />);
    for (const link of screen.getAllByRole("link")) {
      expect(link).not.toHaveAttribute("aria-current");
    }
  });
});
