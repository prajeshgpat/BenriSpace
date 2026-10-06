import { renderHook } from "@testing-library/react";
import type { Map as MaplibreMap } from "maplibre-gl";
import { beforeEach, describe, expect, it, vi } from "vitest";

const gl = vi.hoisted(() => ({ markers: [] as { element: HTMLElement; removed: boolean }[] }));

vi.mock("maplibre-gl", () => {
  class MarkerStub {
    element: HTMLElement;
    entry: { element: HTMLElement; removed: boolean };
    constructor(options: { element: HTMLElement }) {
      this.element = options.element;
      this.entry = { element: options.element, removed: false };
    }
    setLngLat() {
      return this;
    }
    addTo() {
      gl.markers.push(this.entry);
      return this;
    }
    remove() {
      this.entry.removed = true;
    }
  }
  return { Marker: MarkerStub };
});

import type { TripOverlay } from "@/hooks/useTripPlanner";
import type { AreaGeometry } from "@/lib/api/types";

import { useTriangulationLayers } from "./useTriangulationLayers";

const polygon: AreaGeometry = {
  type: "MultiPolygon",
  coordinates: [[[[-74, 40], [-73.9, 40], [-73.9, 40.1], [-74, 40]]]],
};

function overlay(): TripOverlay {
  return {
    anchors: [
      { index: 0, label: "Home", lat: 40, lon: -74, geometry: polygon },
      { index: 1, label: "Work", lat: 40.1, lon: -73.9, geometry: polygon },
    ],
    combined: polygon,
    pins: [
      { index: 0, label: "Home", lat: 40, lon: -74 },
      { index: 1, label: "Work", lat: 40.1, lon: -73.9 },
    ],
  };
}

function fakeMap() {
  const layers = new Map<string, { id: string; paint?: Record<string, unknown> }>();
  const sources = new Map<string, { setData: ReturnType<typeof vi.fn> }>();
  const handlers: Record<string, () => void> = {};
  const map = {
    getStyle: () => ({
      layers: [
        { id: "road", type: "line" },
        { id: "labels", type: "symbol" },
      ],
    }),
    addSource: (id: string) => sources.set(id, { setData: vi.fn() }),
    getSource: (id: string) => sources.get(id),
    removeSource: (id: string) => sources.delete(id),
    addLayer: vi.fn((layer: { id: string }) => layers.set(layer.id, layer)),
    getLayer: (id: string) => layers.get(id),
    removeLayer: (id: string) => layers.delete(id),
    on: (event: string, fn: () => void) => {
      handlers[event] = fn;
    },
    off: vi.fn(),
    once: vi.fn(),
  };
  return { map, layers, sources, handlers };
}

beforeEach(() => {
  gl.markers = [];
});

describe("useTriangulationLayers", () => {
  it("adds per-place and overlap layers with their dash patterns and data", () => {
    const fake = fakeMap();
    const ref = { current: fake.map as unknown as MaplibreMap };
    renderHook(() => useTriangulationLayers({ mapRef: ref, ready: true, theme: "light", overlay: overlay() }));

    expect([...fake.layers.keys()]).toEqual(
      expect.arrayContaining([
        "tri-anchor-0-fill",
        "tri-anchor-1-line",
        "tri-anchor-2-casing",
        "tri-overlap-fill",
        "tri-overlap-line",
      ]),
    );
    expect(fake.layers.get("tri-anchor-0-line")!.paint).toMatchObject({ "line-color": "#c026d3", "line-width": 3 });
    expect(fake.layers.get("tri-anchor-0-line")!.paint).not.toHaveProperty("line-dasharray");
    expect(fake.layers.get("tri-anchor-1-line")!.paint).toMatchObject({ "line-color": "#ea580c", "line-dasharray": [3, 1.5] });
    expect(fake.layers.get("tri-anchor-2-line")!.paint).toMatchObject({ "line-dasharray": [1, 1.5] });
    expect(fake.layers.get("tri-overlap-fill")!.paint).toMatchObject({ "fill-opacity": 0.25 });
    expect(fake.layers.get("tri-overlap-line")!.paint).toMatchObject({ "line-color": "#111827", "line-width": 4.5 });
    const data = fake.sources.get("tri-areas")!.setData.mock.calls[0][0] as { features: unknown[] };
    expect(data.features).toHaveLength(3);
  });

  it("uses the dark palette and rebuilds on style.load", () => {
    const fake = fakeMap();
    const ref = { current: fake.map as unknown as MaplibreMap };
    renderHook(() => useTriangulationLayers({ mapRef: ref, ready: true, theme: "dark", overlay: overlay() }));
    expect(fake.layers.get("tri-overlap-line")!.paint).toMatchObject({ "line-color": "#f8fafc" });
    expect(fake.layers.get("tri-overlap-fill")!.paint).toMatchObject({ "fill-opacity": 0.18 });
    // A style reload drops our layers; style.load puts them back.
    fake.layers.clear();
    fake.sources.clear();
    fake.handlers["style.load"]();
    expect(fake.layers.has("tri-overlap-line")).toBe(true);
  });

  it("adds numbered pins in the anchor colours and removes everything on cleanup", () => {
    const fake = fakeMap();
    const ref = { current: fake.map as unknown as MaplibreMap };
    const view = renderHook(() =>
      useTriangulationLayers({ mapRef: ref, ready: true, theme: "light", overlay: overlay() }),
    );
    expect(gl.markers.map((m) => m.element.textContent)).toEqual(["★", "1"]);
    expect(gl.markers[1].element.style.background).toContain("rgb(234, 88, 12)");
    expect(gl.markers[1].element.getAttribute("aria-label")).toBe("Point 1");

    view.unmount();
    expect(gl.markers.every((m) => m.removed)).toBe(true);
    expect(fake.layers.size).toBe(0);
    expect(fake.sources.size).toBe(0);
  });

  it("does nothing without an overlay or before the map is ready", () => {
    const fake = fakeMap();
    const ref = { current: fake.map as unknown as MaplibreMap };
    renderHook(() => useTriangulationLayers({ mapRef: ref, ready: true, theme: "light", overlay: null }));
    renderHook(() => useTriangulationLayers({ mapRef: ref, ready: false, theme: "light", overlay: overlay() }));
    expect(fake.layers.size).toBe(0);
    expect(gl.markers).toHaveLength(0);
  });
});
