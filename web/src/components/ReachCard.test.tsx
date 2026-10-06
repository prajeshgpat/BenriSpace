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
  it("fetches on toggle and hands the polygon to the map", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const onReach = vi.fn();
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach }}
        onReach={onReach}
      />,
    );
    expect(getReach).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Show on map" }));
    await waitFor(() => expect(onReach).toHaveBeenCalledWith(SQUARE));
    expect(getReach.mock.calls[0].slice(0, 4)).toEqual([40.7, -74, "drive", 15]);
    expect(screen.getByRole("status").textContent).toContain("12.3 sq mi within 15 min");
  });

  it("switches mode and minutes, and says when the area is an estimate", async () => {
    const getReach = vi.fn().mockResolvedValue(reach({ method: "estimate", mode: "walk" }));
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach }}
        onReach={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show on map" }));
    fireEvent.click(screen.getByRole("button", { name: "Walk" }));
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["walk", 10]));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("straight-line circle"),
    );
  });

  it("defaults to walking where people walk, stepping by 5 minutes from 5", async () => {
    const getReach = vi.fn().mockResolvedValue(reach({ mode: "walk" }));
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        travelMode="walk"
        client={{ getReach }}
        onReach={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show on map" }));
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["walk", 10]));
    const fewer = screen.getByRole("button", { name: "Fewer minutes" });
    fireEvent.click(fewer);
    fireEvent.click(fewer);
    expect(screen.getByText("5 min")).toBeTruthy();
    expect((fewer as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "More minutes" }));
    expect(screen.getByText("10 min")).toBeTruthy();
  });

  it("steps every mode by 5 minutes: train up to 45, drive up to 60", () => {
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach: vi.fn().mockResolvedValue(reach()) }}
        onReach={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Train" }));
    const seen = [];
    const fewer = screen.getByRole("button", { name: "Fewer minutes" });
    while (!(fewer as HTMLButtonElement).disabled) fireEvent.click(fewer);
    const more = screen.getByRole("button", { name: "More minutes" });
    for (;;) {
      seen.push(Number(screen.getByText(/^\d+ min$/).textContent?.split(" ")[0]));
      if ((more as HTMLButtonElement).disabled) break;
      fireEvent.click(more);
    }
    expect(seen).toEqual([5, 10, 15, 20, 25, 30, 35, 40, 45]);
    fireEvent.click(screen.getByRole("button", { name: "Drive" }));
    expect(screen.getByText("15 min")).toBeTruthy();
    while (!(more as HTMLButtonElement).disabled) fireEvent.click(more);
    expect(screen.getByText("60 min")).toBeTruthy();
  });

  it("clears the map when turned off and shows an error", async () => {
    const getReach = vi.fn().mockRejectedValue(new Error("boom"));
    const onReach = vi.fn();
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach }}
        onReach={onReach}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show on map" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn"));
    fireEvent.click(screen.getByRole("button", { name: "Hide on map" }));
    await waitFor(() => expect(onReach).toHaveBeenLastCalledWith(null));
  });

  it("renders nothing without coordinates", () => {
    const { container } = render(
      <ReachCard coordinates={null} client={{ getReach: vi.fn() }} onReach={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
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
