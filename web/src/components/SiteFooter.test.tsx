import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SiteFooter } from "./SiteFooter";

describe("SiteFooter", () => {
  it("credits OpenStreetMap, its license and the other data sources", () => {
    render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");

    expect(
      within(footer).getByRole("link", { name: "OpenStreetMap contributors" }),
    ).toHaveAttribute("href", "https://www.openstreetmap.org/copyright");
    expect(within(footer).getByRole("link", { name: "ODbL" })).toHaveAttribute(
      "href",
      "https://opendatacommons.org/licenses/odbl/",
    );
    for (const name of [
      "OpenFreeMap",
      "OpenMapTiles",
      "LocationIQ",
      "Photon",
      "Nominatim",
      "NYC Open Data",
      "MTA",
      "NJ Transit",
    ]) {
      expect(within(footer).getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("opens external credits safely in a new tab", () => {
    render(<SiteFooter />);
    const link = screen.getByRole("link", { name: "OpenFreeMap" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });
});
