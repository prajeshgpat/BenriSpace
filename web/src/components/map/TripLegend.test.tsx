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
    render(<TripLegend overlay={overlay()} status="ready" />);
    const group = screen.getByRole("group", { name: "Travel areas legend" });
    expect(group).toHaveTextContent("POI Overlap");
    expect(group).not.toHaveTextContent("Searched place");
    expect(group).not.toHaveTextContent("Point of interest");
  });

  it("shows the searched place when the areas do not overlap", () => {
    render(<TripLegend overlay={overlay()} status="empty" />);
    const group = screen.getByRole("group", { name: "Travel areas legend" });
    expect(group).toHaveTextContent("Searched place");
    expect(group).not.toHaveTextContent("Overlap");
    expect(group).not.toHaveTextContent("Point of interest");
  });

  it("leaves the searched place out until its area is drawn", () => {
    render(
      <TripLegend
        overlay={overlay({ anchors: [{ index: 0, label: "Home", lat: 40.7, lon: -74, geometry: null }] })}
        status="loading"
      />,
    );
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("renders nothing without anything to explain", () => {
    render(
      <TripLegend overlay={{ anchors: [], combined: null, pins: [] }} status="idle" />,
    );
    expect(screen.queryByRole("group")).toBeNull();
  });
});
