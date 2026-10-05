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
    expect(getReach.mock.calls[0].slice(0, 4)).toEqual([40.7, -74, "drive", 30]);
    expect(screen.getByRole("status").textContent).toContain("12.3 sq mi within 30 min");
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
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["walk", 15]));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("straight-line circle"),
    );
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
