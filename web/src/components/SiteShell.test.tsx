import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SiteShell } from "./SiteShell";

const navigation = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));

beforeEach(() => {
  navigation.pathname = "/";
});

describe("SiteShell", () => {
  it("links the two sections and marks the current one", () => {
    render(<SiteShell>content</SiteShell>);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav).getByRole("link", { name: "Score an address" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(nav).getByRole("link", { name: "Explore the map" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      within(nav).getByRole("link", { name: "Explore the map" }),
    ).toHaveAttribute("href", "/map");
  });

  it("marks the map page current there", () => {
    navigation.pathname = "/map";
    render(<SiteShell>content</SiteShell>);
    expect(
      screen.getByRole("link", { name: "Explore the map" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("keeps the brand as an accessible home link", () => {
    render(<SiteShell>content</SiteShell>);
    expect(screen.getByRole("link", { name: "BenriSpace" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("credits OpenStreetMap, its license and the other data sources on every page", () => {
    for (const pathname of ["/", "/map"]) {
      navigation.pathname = pathname;
      const { unmount } = render(<SiteShell>content</SiteShell>);
      const footer = screen.getByRole("contentinfo");

      expect(
        within(footer).getByRole("link", {
          name: "OpenStreetMap contributors",
        }),
      ).toHaveAttribute("href", "https://www.openstreetmap.org/copyright");
      expect(
        within(footer).getByRole("link", { name: "ODbL" }),
      ).toHaveAttribute("href", "https://opendatacommons.org/licenses/odbl/");
      for (const name of [
        "OpenFreeMap",
        "OpenMapTiles",
        "Photon",
        "Nominatim",
        "NYC Open Data",
        "MTA",
        "NJ Transit",
      ]) {
        expect(within(footer).getByRole("link", { name })).toBeInTheDocument();
      }
      unmount();
    }
  });

  it("opens external credits safely in a new tab", () => {
    render(<SiteShell>content</SiteShell>);
    const link = screen.getByRole("link", { name: "OpenFreeMap" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });
});
