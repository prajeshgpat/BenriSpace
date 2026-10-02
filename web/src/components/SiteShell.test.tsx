import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SiteShell } from "./SiteShell";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

describe("SiteShell", () => {
  it("keeps the brand as an accessible home link", () => {
    render(<SiteShell>content</SiteShell>);
    expect(screen.getByRole("link", { name: "BenriSpace" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("has the menu tabs and the theme switch", () => {
    render(<SiteShell>content</SiteShell>);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link")).toHaveLength(4);
    expect(
      screen.getByRole("button", { name: "Switch to dark mode" }),
    ).toBeInTheDocument();
  });

  it("puts the lightbulb, settings and Login on the right, Login last", () => {
    render(<SiteShell>content</SiteShell>);
    const header = screen.getByRole("banner");
    const controls = within(header)
      .getAllByRole("link")
      .concat(within(header).getAllByRole("button"))
      .filter((el) => !within(screen.getByRole("navigation", { name: "Main" })).queryAllByRole("link").includes(el as HTMLElement))
      .filter((el) => el.getAttribute("href") !== "/");
    const order = controls
      .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
      .map((el) => el.getAttribute("aria-label") ?? el.textContent);
    expect(order).toEqual(["Switch to dark mode", "Settings", "Login"]);
  });

  it("offers a skip link to the main content", () => {
    render(<SiteShell>content</SiteShell>);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute(
      "href",
      "#main",
    );
  });
});
