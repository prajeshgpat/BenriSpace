import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlacePin } from "@/lib/api/types";
import { keyPins } from "@/lib/map/placePins";

const gl = vi.hoisted(() => ({
  removed: 0,
  created: 0,
  handlers: {} as Record<string, () => void>,
  zoom: 14,
}));

vi.mock("maplibre-gl", () => {
  class MarkerStub {
    element: HTMLElement;
    constructor(options: { element: HTMLElement }) {
      this.element = options.element;
      gl.created += 1;
    }
    setLngLat() {
      return this;
    }
    addTo() {
      document.body.appendChild(this.element);
      return this;
    }
    remove() {
      gl.removed += 1;
      this.element.remove();
    }
  }
  return { Marker: MarkerStub };
});

import { PlacePins } from "./PlacePins";

// 1 degree of longitude/latitude = 100000 px, so 0.0001 degrees = 10 px.
function makeMap() {
  return {
    project: ([lon, lat]: [number, number]) => ({ x: (lon + 74) * 1e5, y: (40 - lat) * 1e5 }),
    getZoom: () => gl.zoom,
    fitBounds: vi.fn(),
    on: (event: string, handler: () => void) => {
      gl.handlers[event] = handler;
    },
    off: vi.fn(),
  };
}

const place = (factor: PlacePin["factor"], name: string, lon: number, lat = 40): PlacePin => ({
  factor,
  name,
  brand: null,
  category: factor,
  latitude: lat,
  longitude: lon,
  distanceMi: 0.2,
});

beforeEach(() => {
  gl.removed = 0;
  gl.created = 0;
  gl.handlers = {};
  gl.zoom = 14;
  document.body.innerHTML = "";
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList,
  );
});

describe("PlacePins", () => {
  const pins = keyPins([
    place("restaurant", "Pasta", -74),
    place("restaurant", "Ramen", -73.9999),
    place("bar", "Pub", -73.9998),
    place("cafe", "Joe", -73.5),
  ]);

  it("renders one labelled pin per far-apart place and one labelled cluster", () => {
    const map = makeMap();
    render(<PlacePins map={map as never} pins={pins} />);
    expect(screen.getByRole("button", { name: "3 places: 2 restaurants, 1 bar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Joe · Cafe · 0.2 mi" })).toBeInTheDocument();
    expect(gl.created).toBe(2);
  });

  it("zooms to the members of a cluster on click, without bubbling", () => {
    const map = makeMap();
    const outer = vi.fn();
    document.body.addEventListener("click", outer);
    render(<PlacePins map={map as never} pins={pins} />);
    fireEvent.click(screen.getByRole("button", { name: /3 places/ }));
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    const [bounds, options] = map.fitBounds.mock.calls[0];
    expect(bounds).toEqual([
      [-74, 40],
      [-73.9998, 40],
    ]);
    expect(options).toMatchObject({ padding: 80, maxZoom: 18 });
    expect(outer).not.toHaveBeenCalled();
  });

  it("lists the members instead when zooming cannot split the cluster", () => {
    gl.zoom = 18;
    const map = makeMap();
    render(<PlacePins map={map as never} pins={pins} />);
    fireEvent.click(screen.getByRole("button", { name: /3 places/ }));
    expect(map.fitBounds).not.toHaveBeenCalled();
    expect(screen.getByRole("list", { name: /3 places/ })).toHaveTextContent("Ramen");
  });

  it("keeps unchanged markers when the map moves and removes them on unmount", () => {
    const map = makeMap();
    const view = render(<PlacePins map={map as never} pins={pins} />);
    act(() => gl.handlers.moveend?.());
    expect(gl.created).toBe(2);
    expect(gl.removed).toBe(0);
    view.unmount();
    expect(gl.removed).toBe(2);
  });

  it("draws nothing without a map or pins", () => {
    render(<PlacePins map={null} pins={pins} />);
    render(<PlacePins map={makeMap() as never} pins={[]} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
