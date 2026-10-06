import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const gl = vi.hoisted(() => ({
  calls: [] as string[],
  handlers: {} as Record<string, () => void>,
  removed: false,
  elements: [] as HTMLElement[],
  layers: [] as { id: string; [k: string]: unknown }[],
}));

vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));
vi.mock("maplibre-gl", () => {
  class MapStub {
    constructor() {
      gl.removed = false;
      gl.handlers = {};
    }
    on(event: string, a: unknown, b?: unknown) {
      if (typeof a === "function") gl.handlers[event] = a as () => void;
      void b;
    }
    off() {}
    addControl() {}
    getZoom() {
      return 10;
    }
    jumpTo() {}
    fitBounds() {}
    flyTo() {}
    getContainer() {
      return { clientHeight: 600 };
    }
    getStyle() {
      return { layers: gl.layers };
    }
    addSource() {}
    addLayer(layer: { id: string }, before?: string) {
      const i = before ? gl.layers.findIndex((l) => l.id === before) : -1;
      gl.layers.splice(i < 0 ? gl.layers.length : i, 0, layer);
    }
    removeLayer(id: string) {
      gl.layers.splice(gl.layers.findIndex((l) => l.id === id), 1);
    }
    getSource() {
      return { setData() {} };
    }
    getLayer() {
      return undefined;
    }
    setFilter() {}
    setPaintProperty() {}
    getBounds() {
      return { toArray: () => [[-74, 40], [-73, 41]] };
    }
    getCenter() {
      return { lat: 40, lng: -74 };
    }
    getCanvas() {
      return { style: {} };
    }
    touchZoomRotate = { disableRotation() {} };
    keyboard = { disableRotation() {} };
    remove() {
      gl.calls.push("map.remove");
      gl.removed = true;
    }
  }
  class MarkerStub {
    element: HTMLElement;
    constructor(options: { element: HTMLElement }) {
      this.element = options.element;
    }
    setLngLat() {
      return this;
    }
    addTo() {
      gl.elements.push(this.element);
      return this;
    }
    remove() {
      // The real one dereferences the map's DOM and throws once it is gone.
      if (gl.removed) throw new TypeError("null is not an object (evaluating e.parentNode.removeChild)");
      gl.calls.push("marker.remove");
    }
  }
  return {
    Map: MapStub,
    Marker: MarkerStub,
    NavigationControl: class {},
    AttributionControl: class {},
    setWorkerUrl: () => {},
  };
});

import { MapCanvas } from "./MapCanvas";

beforeEach(() => {
  gl.calls = [];
  gl.elements = [];
  gl.layers = [
    { id: "water", type: "fill", source: "o", "source-layer": "water" },
    { id: "label", type: "symbol", source: "o" },
  ];
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList,
  );
});

describe("MapCanvas teardown", () => {
  it("removes markers and pins before the map and never throws on unmount", () => {
    const view = render(
      <MapCanvas
        initialView={{ lat: 40, lon: -74, zoom: 12 }}
        cells={{ type: "FeatureCollection", features: [] } as never}
        markers={[{ id: "a", rank: 1, lat: 40, lon: -74, label: "x" }]}
        activeMarkerId={null}
        highlightGeohash={null}
        theme="light"
        pin={{ lat: 40, lon: -74 }}
        previewPin={{ lat: 40.1, lon: -74.1 }}
        flyRequest={null}
        onViewportChange={() => {}}
        onCellClick={() => {}}
        onMarkerClick={() => {}}
        onUnavailable={() => {}}
      />,
    );
    act(() => gl.handlers.load?.());
    expect(() => view.unmount()).not.toThrow();
    const last = gl.calls.lastIndexOf("map.remove");
    expect(last).toBe(gl.calls.length - 1);
    expect(gl.calls.filter((c) => c === "marker.remove").length).toBeGreaterThanOrEqual(3);
  });
});

describe("MapCanvas water mask", () => {
  it("draws the basemap water above the cells and below the area layers, once", () => {
    render(
      <MapCanvas
        initialView={{ lat: 40, lon: -74, zoom: 12 }}
        cells={{ type: "FeatureCollection", features: [] } as never}
        markers={[]}
        activeMarkerId={null}
        highlightGeohash={null}
        theme="light"
        pin={null}
        previewPin={null}
        flyRequest={null}
        onViewportChange={() => {}}
        onCellClick={() => {}}
        onMarkerClick={() => {}}
        onUnavailable={() => {}}
      />,
    );
    act(() => gl.handlers["style.load"]?.());
    const ids = gl.layers.map((l) => l.id);
    expect(ids.filter((id) => id === "benri-water:water")).toHaveLength(1);
    const water = ids.indexOf("benri-water:water");
    expect(water).toBeGreaterThan(ids.indexOf("cells-fill"));
    expect(water).toBeLessThan(ids.indexOf("area-fill"));
  });
});

describe("MapCanvas marker tooltips", () => {
  it("gives a ranked marker a name-and-score tooltip and a descriptive label", () => {
    render(
      <MapCanvas
        initialView={{ lat: 40, lon: -74, zoom: 12 }}
        cells={{ type: "FeatureCollection", features: [] } as never}
        markers={[
          {
            id: "a",
            rank: 1,
            lat: 40,
            lon: -74,
            label: "Park Slope, Brooklyn, score 87, rank 1. Show details",
            tooltip: "Park Slope, Brooklyn \u00b7 87",
          },
        ]}
        activeMarkerId={null}
        highlightGeohash={null}
        theme="light"
        pin={null}
        previewPin={null}
        flyRequest={null}
        onViewportChange={() => {}}
        onCellClick={() => {}}
        onMarkerClick={() => {}}
        onUnavailable={() => {}}
      />,
    );
    act(() => gl.handlers.load?.());
    const button = gl.elements.find((el) => el.dataset.markerId === "a")!;
    expect(button.getAttribute("aria-label")).toContain("Park Slope, Brooklyn");
    expect(button.getAttribute("aria-label")).toContain("87");
    const tip = button.querySelector("span")!;
    expect(tip).toHaveTextContent("Park Slope, Brooklyn \u00b7 87");
    expect(tip).toHaveAttribute("aria-hidden", "true");
  });
});
