import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseReach } from "@/lib/api/client";
import type { AreaGeometry, Reach } from "@/lib/api/types";

import { ReachCard } from "./ReachCard";

const SQUARE: AreaGeometry = {
  type: "MultiPolygon",
  coordinates: [
    [
      [
        [-74, 40],
        [-73.9, 40],
        [-73.9, 40.1],
        [-74, 40],
      ],
    ],
  ],
};

function reach(overrides: Partial<Reach> = {}): Reach {
  return {
    mode: "drive",
    minutes: 30,
    method: "network",
    areaSqMi: 12.34,
    geometry: SQUARE,
    ...overrides,
  };
}

describe("ReachCard", () => {
  const SWITCH = { name: "Show travel time on the map" };
  const here = { lat: 40.7, lon: -74 };

  it("fetches with the given mode and minutes and hands the polygon to the map", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const onReach = vi.fn();
    render(
      <ReachCard coordinates={here} mode="drive" minutes={15} client={{ getReach }} onReach={onReach} />,
    );
    const toggle = screen.getByRole("switch", SWITCH);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(onReach).toHaveBeenCalledWith(SQUARE));
    expect(getReach.mock.calls[0].slice(0, 4)).toEqual([40.7, -74, "drive", 15]);
    expect(screen.getByText("Drive, 15 min")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("12.3 sq mi within 15 min");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    await waitFor(() => expect(onReach).toHaveBeenLastCalledWith(null));
  });

  it("has no mode buttons or stepper: the search box owns them", () => {
    render(
      <ReachCard
        coordinates={here}
        mode="transit"
        minutes={20}
        client={{ getReach: vi.fn().mockResolvedValue(reach()) }}
        onReach={() => {}}
      />,
    );
    expect(screen.getByText("Train, 20 min")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Walk" })).toBeNull();
    expect(screen.queryByRole("button", { name: "More minutes" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Travel mode" })).toBeNull();
  });

  it("refetches when the mode or minutes change, and says when the area is an estimate", async () => {
    const getReach = vi.fn().mockResolvedValue(reach({ method: "estimate", mode: "walk" }));
    const props = { coordinates: here, client: { getReach }, onReach: () => {} };
    const { rerender } = render(<ReachCard {...props} mode="drive" minutes={15} />);
    rerender(<ReachCard {...props} mode="walk" minutes={10} />);
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["walk", 10]));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("straight-line circle"),
    );
    rerender(<ReachCard {...props} mode="walk" minutes={15} />);
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["walk", 15]));
  });

  it("when suspended, clears the area, disables the switch and says why", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const onReach = vi.fn();
    const props = { coordinates: here, mode: "drive" as const, minutes: 15, client: { getReach }, onReach };
    const { rerender } = render(<ReachCard {...props} />);
    await waitFor(() => expect(onReach).toHaveBeenCalledWith(SQUARE));
    const calls = getReach.mock.calls.length;
    rerender(<ReachCard {...props} suspended />);
    const toggle = screen.getByRole("switch", SWITCH) as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    await waitFor(() => expect(onReach).toHaveBeenLastCalledWith(null));
    expect(getReach.mock.calls.length).toBe(calls);
    expect(
      screen.getByText("Travel areas are showing for your points of interest."),
    ).toBeTruthy();
    expect(screen.getByText("Drive, 15 min")).toBeTruthy();
  });

  it("stays on with the same mode and minutes when the place changes", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const props = { mode: "transit" as const, minutes: 25, client: { getReach }, onReach: () => {} };
    const { rerender } = render(<ReachCard coordinates={here} {...props} />);
    rerender(<ReachCard coordinates={null} {...props} />);
    rerender(<ReachCard coordinates={{ lat: 40.8, lon: -73.9 }} {...props} />);
    expect(screen.getByRole("switch", SWITCH).getAttribute("aria-checked")).toBe("true");
    await waitFor(() =>
      expect(getReach.mock.calls.at(-1)?.slice(0, 4)).toEqual([40.8, -73.9, "transit", 25]),
    );
  });

  it("clears the map when switched off and shows an error", async () => {
    const getReach = vi.fn().mockRejectedValue(new Error("boom"));
    const onReach = vi.fn();
    render(
      <ReachCard coordinates={here} mode="drive" minutes={15} client={{ getReach }} onReach={onReach} />,
    );
    const toggle = screen.getByRole("switch", SWITCH);
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn"));
    fireEvent.click(toggle);
    await waitFor(() => expect(onReach).toHaveBeenLastCalledWith(null));
  });

  it("says when nothing is reachable", async () => {
    const getReach = vi.fn().mockResolvedValue(reach({ geometry: null }));
    render(
      <ReachCard coordinates={here} mode="walk" minutes={5} client={{ getReach }} onReach={() => {}} />,
    );
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Nothing reachable"),
    );
  });

  it("is shown on but disabled without a place, and never fetches", () => {
    const getReach = vi.fn();
    render(
      <ReachCard coordinates={null} mode="drive" minutes={15} client={{ getReach }} onReach={() => {}} />,
    );
    const toggle = screen.getByRole("switch", SWITCH) as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(getReach).not.toHaveBeenCalled();
  });
});

describe("parseReach", () => {
  it("parses the isochrone response and rejects junk", () => {
    const parsed = parseReach({
      latitude: 40,
      longitude: -74,
      isochrone: {
        mode: "walk",
        minutes: 15,
        method: "network",
        cellCount: 3,
        areaSqMi: 0.7,
        geometry: SQUARE,
      },
    });
    expect(parsed.mode).toBe("walk");
    expect(parsed.geometry?.type).toBe("MultiPolygon");
    expect(() => parseReach({ isochrone: { mode: "bike" } })).toThrow();
  });
});
