import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TripOverlay } from "@/hooks/useTripPlanner";
import type { AreaGeometry } from "@/lib/api/types";

import { TripLegend } from "./TripLegend";

const geometry: AreaGeometry = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };

function overlay(over: Partial<TripOverlay> = {}): TripOverlay {
  return {
    anchors: [{ index: 0, label: "Home", lat: 40.7, lon: -74, geometry }],
    combined: geometry,
    pins: [
      { index: 0, label: "Home", lat: 40.7, lon: -74 },
      { index: 1, label: "Park", lat: 40.75, lon: -73.97 },
    ],
    ...over,
  };
}

describe("TripLegend", () => {
  it("shows POI Overlap, not the searched place or numbered points, once there is an overlap", () => {
    render(<TripLegend overlay={overlay()} status="ready" reach={null} />);
    const group = screen.getByRole("group", { name: "Travel areas legend" });
    expect(group).toHaveTextContent("POI Overlap");
    expect(group).not.toHaveTextContent("Searched place");
    expect(group).not.toHaveTextContent("Point of interest");
  });

  it("shows the searched place when the areas do not overlap", () => {
    render(<TripLegend overlay={overlay()} status="empty" reach={null} />);
    const group = screen.getByRole("group", { name: "Travel areas legend" });
    expect(group).toHaveTextContent("Searched place");
    expect(group).not.toHaveTextContent("Overlap");
    expect(group).not.toHaveTextContent("Point of interest");
  });

  it("explains the pink boundary of a searched place on its own", () => {
    render(
      <TripLegend overlay={null} status={null} reach={{ mode: "drive", minutes: 10, estimate: false }} />,
    );
    const group = screen.getByRole("group", { name: "Travel areas legend" });
    expect(group).toHaveTextContent("Searched place");
    expect(group).toHaveTextContent("Within 10 min by car");
    expect(group).not.toHaveTextContent("estimate");
  });

  it("names the mode and says when the boundary is a straight-line estimate", () => {
    render(
      <TripLegend overlay={null} status={null} reach={{ mode: "transit", minutes: 15, estimate: true }} />,
    );
    expect(screen.getByRole("group", { name: "Travel areas legend" })).toHaveTextContent(
      "Within 15 min by train (straight-line estimate)",
    );
  });

  it("shows the searched place over an overlap when its boundary is switched on", () => {
    render(
      <TripLegend overlay={overlay()} status="ready" reach={{ mode: "walk", minutes: 10, estimate: false }} />,
    );
    const group = screen.getByRole("group", { name: "Travel areas legend" });
    expect(group).toHaveTextContent("Within 10 min on foot");
    expect(group).toHaveTextContent("POI Overlap");
  });

  it("leaves the searched place out until its area is drawn", () => {
    render(
      <TripLegend
        overlay={overlay({ anchors: [{ index: 0, label: "Home", lat: 40.7, lon: -74, geometry: null }] })}
        status={null}
        reach={null}
      />,
    );
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("renders nothing without anything to explain", () => {
    render(<TripLegend overlay={null} status={null} reach={null} />);
    expect(screen.queryByRole("group")).toBeNull();
  });
});
