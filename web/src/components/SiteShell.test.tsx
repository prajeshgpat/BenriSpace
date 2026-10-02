import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SiteShell } from "./SiteShell";

describe("SiteShell", () => {
  it("keeps the brand as an accessible home link", () => {
    render(<SiteShell>content</SiteShell>);
    expect(screen.getByRole("link", { name: "BenriSpace" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("has nothing to navigate between", () => {
    render(<SiteShell>content</SiteShell>);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("offers a skip link to the main content", () => {
    render(<SiteShell>content</SiteShell>);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute(
      "href",
      "#main",
    );
  });
});
