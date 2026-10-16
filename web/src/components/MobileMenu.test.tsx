import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MobileMenu } from "./MobileMenu";

const nav = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

const button = () => screen.getByRole("button", { name: "Menu" });
const panel = () => screen.getByRole("navigation", { name: "Site menu" });

beforeEach(() => {
  nav.pathname = "/";
});

describe("MobileMenu", () => {
  it("is closed to start with and the button reports it", () => {
    render(<MobileMenu />);
    expect(button()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("opens a labelled nav with every page, the theme switch and focus on the first link", async () => {
    const user = userEvent.setup();
    render(<MobileMenu />);
    await user.click(button());
    expect(button()).toHaveAttribute("aria-expanded", "true");
    expect(button()).toHaveAttribute("aria-controls", panel().id);
    const links = within(panel()).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "BenriSpace",
      "Map",
      "For Business",
      "Developers",
      "Pricing",
      "Settings",
      "Login",
    ]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/",
      "/app",
      "/business",
      "/docs",
      "/pricing",
      "/settings",
      "/login",
    ]);
    expect(
      within(panel()).getByRole("button", { name: /Switch to (dark|light) mode/ }),
    ).toBeInTheDocument();
    expect(links[0]).toHaveFocus();
  });

  it("marks the current page", async () => {
    nav.pathname = "/pricing";
    const user = userEvent.setup();
    render(<MobileMenu />);
    await user.click(button());
    expect(within(panel()).getByRole("link", { name: "Pricing" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(panel()).getByRole("link", { name: "Map" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("closes on Escape and returns focus to the button", async () => {
    const user = userEvent.setup();
    render(<MobileMenu />);
    await user.click(button());
    await user.keyboard("{Escape}");
    expect(button()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(button()).toHaveFocus();
  });

  it("closes when the pointer goes down outside, not inside", async () => {
    const user = userEvent.setup();
    render(
      <>
        <p>elsewhere</p>
        <MobileMenu />
      </>,
    );
    await user.click(button());
    await user.click(within(panel()).getByRole("link", { name: "Pricing" }));
    expect(button()).toHaveAttribute("aria-expanded", "false"); // link click closes
    await user.click(button());
    await user.click(screen.getByText("elsewhere"));
    expect(button()).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles with the button", async () => {
    const user = userEvent.setup();
    render(<MobileMenu />);
    await user.click(button());
    await user.click(button());
    expect(button()).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps Tab inside the button and the panel", async () => {
    const user = userEvent.setup();
    render(<MobileMenu />);
    await user.click(button());
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(button()).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(
      within(panel()).getByRole("button", { name: /Switch to/ }),
    ).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(button()).toHaveFocus();
  });

  it("closes when the route changes", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<MobileMenu />);
    await user.click(button());
    nav.pathname = "/app";
    rerender(<MobileMenu />);
    expect(button()).toHaveAttribute("aria-expanded", "false");
  });
});
