import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "@/lib/theme";

import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("switches to dark, remembers it, and switches back", () => {
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    fireEvent.click(screen.getByRole("button", { name: "Switch to light mode" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("starts from a theme chosen earlier", () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    expect(
      screen.getByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();
  });
});
