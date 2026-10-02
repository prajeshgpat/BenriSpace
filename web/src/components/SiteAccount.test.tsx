import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SiteAccount } from "./SiteAccount";

const pathname = vi.hoisted(() => vi.fn(() => "/"));
vi.mock("next/navigation", () => ({ usePathname: pathname }));

describe("SiteAccount", () => {
  it("has a settings icon link followed by Login", () => {
    render(<SiteAccount />);
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/settings", "/login"]);
    expect(links[0]).toHaveAccessibleName("Settings");
    expect(links[1]).toHaveTextContent("Login");
  });

  it("marks the current page", () => {
    pathname.mockReturnValue("/settings");
    render(<SiteAccount />);
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Login" })).not.toHaveAttribute("aria-current");
  });
});
