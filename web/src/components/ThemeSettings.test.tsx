import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "@/lib/theme";

import { ThemeSettings } from "./ThemeSettings";

describe("ThemeSettings", () => {
  it("defaults to the device setting", () => {
    render(<ThemeSettings />);
    expect(screen.getByRole("radio", { name: "Match my device" })).toBeChecked();
  });

  it("saves an explicit choice, and clears it for the device setting", () => {
    render(<ThemeSettings />);

    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    fireEvent.click(screen.getByRole("radio", { name: "Match my device" }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });
});
