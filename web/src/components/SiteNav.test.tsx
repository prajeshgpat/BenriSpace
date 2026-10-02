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
      "Home",
      "App",
      "API",
      "Pricing",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/",
      "/app",
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
    for (const name of ["Home", "App", "API"]) {
      expect(screen.getByRole("link", { name })).not.toHaveAttribute(
        "aria-current",
      );
    }
  });

  it("matches the path exactly, so /app is not Home", () => {
    pathname.mockReturnValue("/app");
    render(<SiteNav />);
    expect(screen.getByRole("link", { name: "App" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("marks Home on /", () => {
    pathname.mockReturnValue("/");
    render(<SiteNav />);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
