import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TravelModePicker } from "./TravelModePicker";

describe("TravelModePicker", () => {
  it("labels its groups with the name and picks a mode's own minutes", () => {
    const onChange = vi.fn();
    render(<TravelModePicker mode="drive" minutes={15} onChange={onChange} name="Point 1" />);
    expect(screen.getByRole("group", { name: "Travel mode for Point 1" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Minutes for Point 1" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Train" }));
    expect(onChange).toHaveBeenCalledWith("transit", 10);
    fireEvent.click(screen.getByRole("button", { name: "More minutes for Point 1" }));
    expect(onChange).toHaveBeenLastCalledWith("drive", 20);
  });

  it("disables everything when disabled and draws walk as a filled person", () => {
    render(<TravelModePicker mode="walk" minutes={5} onChange={() => {}} name="Travel time" disabled />);
    expect(screen.getByRole("group", { name: "Travel mode" })).toBeTruthy();
    for (const b of screen.getAllByRole("button")) expect((b as HTMLButtonElement).disabled).toBe(true);
    const svg = screen.getByRole("button", { name: "Walk" }).querySelector("svg")!;
    expect(svg.getAttribute("stroke")).toBeNull();
    expect(svg.getAttribute("fill")).toBe("currentColor");
    expect(svg.querySelector("path")!.getAttribute("d")!.startsWith("M13.5 5.5")).toBe(true);
  });
});
