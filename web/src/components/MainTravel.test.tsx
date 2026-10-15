import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MainTravel } from "./MainTravel";

function setup(mode: "walk" | "transit" | "drive" = "drive", minutes = 15, showOnMap = true) {
  const onChange = vi.fn();
  const onShowOnMap = vi.fn();
  const view = render(
    <MainTravel
      mode={mode}
      minutes={minutes}
      onChange={onChange}
      showOnMap={showOnMap}
      onShowOnMap={onShowOnMap}
    />,
  );
  const toggle = () => screen.getByRole("button", { name: /^Travel time:/ });
  return { onChange, onShowOnMap, toggle, ...view };
}

const noop = () => {};

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

  it("picking a mode starts it at 10 minutes", () => {
    const { toggle, onChange } = setup();
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("button", { name: "Train" }));
    expect(onChange).toHaveBeenLastCalledWith("transit", 10);
    fireEvent.click(screen.getByRole("button", { name: "Drive" }));
    expect(onChange).toHaveBeenLastCalledWith("drive", 10);
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
    const at = (mode: "walk" | "transit" | "drive", minutes: number) =>
      rerender(
        <MainTravel mode={mode} minutes={minutes} onChange={onChange} showOnMap onShowOnMap={noop} />,
      );
    const more = () => screen.getByRole("button", { name: "More minutes" }) as HTMLButtonElement;
    at("walk", 5);
    expect((screen.getByRole("button", { name: "Fewer minutes" }) as HTMLButtonElement).disabled).toBe(true);
    // Walk tops out at 30, train at 45, drive at 60.
    at("walk", 25);
    expect(more().disabled).toBe(false);
    at("walk", 30);
    expect(more().disabled).toBe(true);
    at("transit", 45);
    expect(more().disabled).toBe(true);
    at("drive", 55);
    expect(more().disabled).toBe(false);
    at("drive", 60);
    expect(more().disabled).toBe(true);
  });

  it("has a Show on map switch for the travel boundary", () => {
    const { toggle, onShowOnMap, rerender } = setup("drive", 10, true);
    fireEvent.click(toggle());
    const show = screen.getByRole("switch", { name: "Show on map" });
    expect(show.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(show);
    expect(onShowOnMap).toHaveBeenLastCalledWith(false);
    rerender(
      <MainTravel mode="drive" minutes={10} onChange={noop} showOnMap={false} onShowOnMap={onShowOnMap} />,
    );
    fireEvent.click(screen.getByRole("switch", { name: "Show on map" }));
    expect(onShowOnMap).toHaveBeenLastCalledWith(true);
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
