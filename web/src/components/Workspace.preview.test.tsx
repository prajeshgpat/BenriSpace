import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { createApiClient, type ApiClient } from "@/lib/api/client";
import type { AreaScore } from "@/lib/api/types";
import {
  jsonResponse,
  liveExplanationBody,
  liveScoreBody,
  makeAreaScore,
} from "@/test/fixtures";

import type { MapCanvas as MapCanvasType } from "./map/MapCanvas";
import { Workspace } from "./Workspace";

type CanvasProps = Parameters<typeof MapCanvasType>[0];

const navigation = vi.hoisted(() => ({
  search: "",
  listeners: new Set<() => void>(),
}));

vi.mock("next/navigation", async () => {
  const subscribe = (listener: () => void) => {
    navigation.listeners.add(listener);
    return () => navigation.listeners.delete(listener);
  };
  return {
    useSearchParams: () => {
      const search = useSyncExternalStore(
        subscribe,
        () => navigation.search,
        () => navigation.search,
      );
      return useMemo(() => new URLSearchParams(search), [search]);
    },
  };
});

const canvas = vi.hoisted(() => ({ props: null as unknown }));
vi.mock("./map/MapCanvas", () => ({
  MapCanvas: (props: unknown) => {
    canvas.props = props;
    return <div data-testid="map" />;
  },
}));
const map = () => canvas.props as CanvasProps;

let pushState: MockInstance<History["pushState"]>;

function setSearch(href: string | URL | null | undefined) {
  const url = String(href ?? "");
  navigation.search = url.includes("?") ? url.slice(url.indexOf("?") + 1) : "";
  act(() => navigation.listeners.forEach((listener) => listener()));
}

const SIMILAR = {
  minSeparationMi: 1,
  priorities: [],
  results: [1, 2].map((i) => ({
    latitude: 40.7 + i / 100,
    longitude: -74,
    direction: "SE",
    distanceLabel: `${i} mi`,
    similarity: 88,
    compositeScore: 71.4,
    areaLabel: `Area bounded by Road ${i}`,
    differences: [{ factor: "transit", label: "transit", delta: 7 }],
    summary: "",
  })),
};

interface Deferred {
  lat: number;
  resolve: (area: AreaScore) => void;
}

function setup(search = "address=350+5th+Ave&lat=40.7484&lon=-73.9857") {
  navigation.search = search;
  const fetchMock = vi.fn<typeof fetch>(async (input) =>
    String(input).includes("/explanation")
      ? jsonResponse(liveExplanationBody)
      : jsonResponse(liveScoreBody),
  );
  const pending: Deferred[] = [];
  const getAreaByCoordinates = vi.fn<ApiClient["getAreaByCoordinates"]>(
    ({ lat }, options) =>
      new Promise<AreaScore>((resolve, reject) => {
        // The selected place resolves at once; previews are held for the test.
        if (lat === 40.7484) return resolve(makeAreaScore());
        pending.push({ lat, resolve });
        options?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  );
  const client: ApiClient = {
    ...createApiClient({ baseUrl: "http://api.test/v1", fetch: fetchMock }),
    getAreaByCoordinates,
    getMapCells: vi.fn(async () => ({
      precision: 5,
      factors: [],
      weights: {},
      weightsVersion: "v1",
      truncated: false,
      geohashes: [],
      scores: [],
    })) as unknown as ApiClient["getMapCells"],
    getMapTop: vi.fn(async () => ({
      factors: [],
      weights: {},
      weightsVersion: "v1",
      results: [],
    })) as unknown as ApiClient["getMapTop"],
    reverseGeocode: vi.fn(async ({ lat, lon }) => ({ label: null, latitude: lat, longitude: lon })),
    getImprove: vi.fn(async () => {
      throw new Error("improve unavailable");
    }),
    getSimilar: vi.fn(async () => SIMILAR as never),
  };
  render(<Workspace client={client} />);
  return { client, pending, getAreaByCoordinates };
}

async function showSimilar(n: number) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: `Show similar area ${n} on map` }));
}

beforeEach(() => {
  navigation.search = "";
  window.history.replaceState(null, "", "/app");
  pushState = vi
    .spyOn(window.history, "pushState")
    .mockImplementation((_data, _unused, url) => setSearch(url));
  vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
});

describe("Workspace: previewing a suggested area", () => {
  it("shows the preview without changing the selected target or URL", async () => {
    setup();
    await screen.findByTestId("composite-score");
    const before = navigation.search;
    const pin = map().pin;

    await showSimilar(1);

    expect(screen.getByRole("region", { name: "Previewed area" })).toBeInTheDocument();
    expect(map().previewPin).toEqual({ lat: SIMILAR.results[0].latitude, lon: -74 });
    expect(map().flyRequest?.bounds).toBeDefined();
    expect(map().pin).toEqual(pin);
    expect(navigation.search).toBe(before);
    expect(pushState).not.toHaveBeenCalled();
    expect(screen.getByTestId("composite-score")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("350 5th Ave");
  });

  it("draws the preview polygon when the area lookup returns, and only for the latest preview", async () => {
    const { pending } = setup();
    await screen.findByTestId("composite-score");

    await showSimilar(1);
    await showSimilar(2);
    await waitFor(() => expect(pending).toHaveLength(2));
    const second = pending.find((p) => Math.abs(p.lat - 40.72) < 1e-6)!;
    // The first request was cancelled; resolving it late must not draw.
    pending.find((p) => Math.abs(p.lat - 40.71) < 1e-6)!.resolve(
      makeAreaScore({ area: { ...makeAreaScore().area, boundedBy: ["Stale"] } }),
    );
    await act(async () => {});
    expect(map().previewAreaGeometry ?? null).toBeNull();

    await act(async () => second.resolve(makeAreaScore()));
    expect(map().previewAreaGeometry).toMatchObject({ type: "Polygon" });
    expect(map().previewPin).toEqual({ lat: SIMILAR.results[1].latitude, lon: -74 });
  });

  it("Back clears the preview and returns to the original place", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByTestId("composite-score");
    await showSimilar(1);

    await user.click(screen.getByRole("button", { name: /^Back to 350 5th Ave/ }));

    expect(screen.queryByRole("region", { name: "Previewed area" })).not.toBeInTheDocument();
    expect(map().previewPin ?? null).toBeNull();
    expect(map().flyRequest?.bounds).toBeDefined();
    expect(pushState).not.toHaveBeenCalled();
    expect(screen.getByTestId("composite-score")).toBeInTheDocument();
  });

  it("Score this area navigates through history and clears the preview", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByTestId("composite-score");
    await showSimilar(1);

    await user.click(screen.getByRole("button", { name: "Score this area" }));

    expect(pushState).toHaveBeenCalledTimes(1);
    expect(String(pushState.mock.calls[0][2])).toContain("lat=40.71");
    expect(screen.queryByRole("region", { name: "Previewed area" })).not.toBeInTheDocument();
    expect(map().previewPin ?? null).toBeNull();
  });

  it("clears the preview on the close button and on a new search", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByTestId("composite-score");
    await showSimilar(1);
    await user.click(screen.getByRole("button", { name: "Close preview" }));
    expect(screen.queryByRole("region", { name: "Previewed area" })).not.toBeInTheDocument();

    await showSimilar(1);
    const field = screen.getByRole("combobox", { name: "Address" });
    await user.clear(field);
    await user.type(field, "1 Main St, Newark{Enter}");
    expect(pushState).toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Previewed area" })).not.toBeInTheDocument();
  });

  it("clears the preview when the map is clicked", async () => {
    setup();
    await screen.findByTestId("composite-score");
    await showSimilar(1);
    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7, lon: -74 }));
    expect(screen.queryByRole("region", { name: "Previewed area" })).not.toBeInTheDocument();
  });
});
