import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const gl = vi.hoisted(() => ({
  calls: [] as string[],
  handlers: {} as Record<string, () => void>,
  removed: false,
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
      return { layers: [] };
    }
    addSource() {}
    addLayer() {}
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
