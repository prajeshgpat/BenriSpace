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

  it("fetches when switched on and hands the polygon to the map", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const onReach = vi.fn();
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach }}
        onReach={onReach}
      />,
    );
    // The switch starts on: the area is fetched and drawn as soon as there is a place.
    const toggle = screen.getByRole("switch", SWITCH);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(onReach).toHaveBeenCalledWith(SQUARE));
    expect(getReach.mock.calls[0].slice(0, 4)).toEqual([40.7, -74, "drive", 15]);
    expect(screen.getByText("15 min")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("12.3 sq mi within 15 min");
    // Switching it off clears the area from the map.
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    await waitFor(() => expect(onReach).toHaveBeenLastCalledWith(null));
  });

  it("switches mode with icon buttons, and says when the area is an estimate", async () => {
    const getReach = vi.fn().mockResolvedValue(reach({ method: "estimate", mode: "walk" }));
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach }}
        onReach={() => {}}
      />,
    );
    const walk = screen.getByRole("button", { name: "Walk" });
    expect(walk.textContent).toBe(""); // an icon, not a word
    fireEvent.click(walk);
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["walk", 10]));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("straight-line circle"),
    );
  });

  it("starts dense places on a 20 min train, stepping by 5 minutes from 5", async () => {
    const getReach = vi.fn().mockResolvedValue(reach({ mode: "transit" }));
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        travelMode="walk"
        client={{ getReach }}
        onReach={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Train" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("20 min")).toBeTruthy();
    await waitFor(() =>
      expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["transit", 20]),
    );
    fireEvent.click(screen.getByRole("button", { name: "Walk" }));
    expect(screen.getByText("10 min")).toBeTruthy();
    const fewer = screen.getByRole("button", { name: "Fewer minutes" });
    fireEvent.click(fewer);
    expect(screen.getByText("5 min")).toBeTruthy();
    expect((fewer as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "More minutes" }));
    expect(screen.getByText("10 min")).toBeTruthy();
  });

  it("defaults non-dense places to a 15 min drive", () => {
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        travelMode="drive"
        client={{ getReach: vi.fn().mockResolvedValue(reach()) }}
        onReach={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Drive" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("15 min")).toBeTruthy();
  });

  it("puts the switch after the mode group, with a filled walking person icon", () => {
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach: vi.fn().mockResolvedValue(reach()) }}
        onReach={() => {}}
      />,
    );
    const modes = screen.getByRole("group", { name: "Travel mode" });
    const toggle = screen.getByRole("switch", SWITCH);
    expect(modes.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const svg = screen.getByRole("button", { name: "Walk" }).querySelector("svg")!;
    expect(svg.getAttribute("stroke")).toBeNull();
    expect(svg.querySelector("path")!.getAttribute("d")!.startsWith("M13.5 5.5")).toBe(true);
  });

  it("when suspended, clears the area, disables the switch and says why", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const onReach = vi.fn();
    const props = { coordinates: { lat: 40.7, lon: -74 }, client: { getReach }, onReach };
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

  it("stays on with the chosen mode and minutes when the place changes", async () => {
    const getReach = vi.fn().mockResolvedValue(reach());
    const props = { client: { getReach }, onReach: () => {} };
    const { rerender } = render(
      <ReachCard coordinates={{ lat: 40.7, lon: -74 }} travelMode="drive" {...props} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Train" }));
    fireEvent.click(screen.getByRole("button", { name: "More minutes" }));
    await waitFor(() => expect(getReach.mock.calls.at(-1)?.slice(2, 4)).toEqual(["transit", 25]));
    // A new place is loading (no coordinates), then arrives with a different default mode.
    rerender(<ReachCard coordinates={null} travelMode={null} {...props} />);
    rerender(<ReachCard coordinates={{ lat: 40.8, lon: -73.9 }} travelMode="walk" {...props} />);
    expect(screen.getByRole("switch", SWITCH).getAttribute("aria-checked")).toBe("true");
    await waitFor(() =>
      expect(getReach.mock.calls.at(-1)?.slice(0, 4)).toEqual([40.8, -73.9, "transit", 25]),
    );
  });

  it("follows the place's own mode until the user picks one", () => {
    const props = { client: { getReach: vi.fn().mockResolvedValue(reach()) }, onReach: () => {} };
    const { rerender } = render(
      <ReachCard coordinates={{ lat: 40.7, lon: -74 }} travelMode="drive" {...props} />,
    );
    expect(screen.getByRole("button", { name: "Drive" }).getAttribute("aria-pressed")).toBe("true");
    rerender(<ReachCard coordinates={{ lat: 40.72, lon: -74.04 }} travelMode="walk" {...props} />);
    expect(screen.getByRole("button", { name: "Train" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("20 min")).toBeTruthy();
  });

  it("clears the map when switched off and shows an error", async () => {
    const getReach = vi.fn().mockRejectedValue(new Error("boom"));
    const onReach = vi.fn();
    render(
      <ReachCard
        coordinates={{ lat: 40.7, lon: -74 }}
        client={{ getReach }}
        onReach={onReach}
      />,
    );
    const toggle = screen.getByRole("switch", SWITCH);
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn"));
    fireEvent.click(toggle);
    await waitFor(() => expect(onReach).toHaveBeenLastCalledWith(null));
  });

  it("is shown on but disabled without a place, and never fetches", () => {
    const getReach = vi.fn();
    render(<ReachCard coordinates={null} client={{ getReach }} onReach={() => {}} />);
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
