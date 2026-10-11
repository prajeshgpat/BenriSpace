import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MainTravel } from "./MainTravel";

function setup(mode: "walk" | "transit" | "drive" = "drive", minutes = 15) {
  const onChange = vi.fn();
  const view = render(<MainTravel mode={mode} minutes={minutes} onChange={onChange} />);
  const toggle = () => screen.getByRole("button", { name: /^Travel time:/ });
  return { onChange, toggle, ...view };
}

describe("MainTravel", () => {
  it("shows the mode and minutes on a closed toggle", () => {
    const { toggle } = setup("transit", 20);
    expect(toggle().getAttribute("aria-label")).toBe("Travel time: Train, 20 minutes");
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByTestId("travel-badge").textContent).toContain("20");
    expect(screen.queryByRole("group", { name: "Travel mode" })).toBeNull();
  });

  it("opens a panel with the modes and a minutes stepper", () => {
    const { toggle } = setup("drive", 15);
    fireEvent.click(toggle());
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Drive" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Walk" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "Walk" }).textContent).toBe("");
  });

  it("picking a mode reports its initial minutes", () => {
    const { toggle, onChange } = setup();
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("button", { name: "Train" }));
    expect(onChange).toHaveBeenLastCalledWith("transit", 20);
    fireEvent.click(screen.getByRole("button", { name: "Walk" }));
    expect(onChange).toHaveBeenLastCalledWith("walk", 10);
  });

  it("steps minutes by 5 and stops at the ends", () => {
    const { toggle, onChange, rerender } = setup("walk", 10);
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("button", { name: "More minutes" }));
    expect(onChange).toHaveBeenLastCalledWith("walk", 15);
    fireEvent.click(screen.getByRole("button", { name: "Fewer minutes" }));
    expect(onChange).toHaveBeenLastCalledWith("walk", 5);
    rerender(<MainTravel mode="walk" minutes={5} onChange={onChange} />);
    expect((screen.getByRole("button", { name: "Fewer minutes" }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<MainTravel mode="drive" minutes={60} onChange={onChange} />);
    expect((screen.getByRole("button", { name: "More minutes" }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<MainTravel mode="transit" minutes={45} onChange={onChange} />);
    expect((screen.getByRole("button", { name: "More minutes" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("closes on an outside press but not an inside one", () => {
    const { toggle } = setup();
    fireEvent.click(toggle());
    fireEvent.pointerDown(screen.getByRole("group", { name: "Travel mode" }));
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    fireEvent.pointerDown(document.body);
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("group", { name: "Travel mode" })).toBeNull();
  });

  it("closes on Escape and returns focus to the toggle", () => {
    const { toggle } = setup();
    fireEvent.click(toggle());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle());
  });

  it("toggles closed with a second click", () => {
    const { toggle } = setup();
    fireEvent.click(toggle());
    fireEvent.click(toggle());
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
  });
});
