import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import type { ApiClient } from "@/lib/api/client";
import type { Bbox, MapCells, MapTop, MapTopResult } from "@/lib/api/types";
import { createSelection } from "@/lib/map/selection";
import { DEFAULT_MAP_STATE, type MapUrlState } from "@/lib/map/url";
import { emptySubScores, stubClient } from "@/test/fixtures";

import type { MapCanvas as MapCanvasType } from "./MapCanvas";
import { MapExplorer } from "./MapExplorer";

type CanvasProps = Parameters<typeof MapCanvasType>[0];

// WebGL does not exist in jsdom. The stand-in records the props the explorer
// passes and lets a test play the part of the map.
const canvas = vi.hoisted(() => ({ props: null as unknown }));
vi.mock("./MapCanvas", () => ({
  MapCanvas: (props: unknown) => {
    canvas.props = props;
    return <div data-testid="map" />;
  },
}));
const map = () => canvas.props as CanvasProps;

const DEFAULTS = { grocery: 1.5, transit: 1.5, cafe: 1 };

function cellsResponse(overrides: Partial<MapCells> = {}): MapCells {
  return {
    precision: 5,
    factors: ["grocery", "transit", "cafe"],
    weights: DEFAULTS,
    weightsVersion: "v1",
    truncated: false,
    geohashes: ["dr5ru", "dr5rv"],
    scores: [40, 90],
    ...overrides,
  };
}

const RESULTS: MapTopResult[] = [
  {
    geohash: "dr5ru7",
    latitude: 40.7546,
    longitude: -73.985,
    score: 99.8,
    metroArea: "nyc",
    subScores: { ...emptySubScores, grocery: 98, transit: 95, cafe: 60 },
  },
  {
    geohash: "dr5rxn",
    latitude: 40.7276,
    longitude: -73.864,
    score: 91.2,
    metroArea: "nyc",
    subScores: { ...emptySubScores, grocery: 70, transit: 90, cafe: 99 },
  },
];

function topResponse(overrides: Partial<MapTop> = {}): MapTop {
  return {
    factors: ["grocery", "transit", "cafe"],
    weights: DEFAULTS,
    weightsVersion: "v1",
    results: RESULTS,
    ...overrides,
  };
}

const VIEWPORT = {
  user: true,
  bbox: [-74.1, 40.6, -73.9, 40.8] as Bbox,
  zoom: 11,
  center: { lat: 40.7, lon: -74 },
};

function setup(initial: MapUrlState = DEFAULT_MAP_STATE, client = {}) {
  const getMapCells = vi.fn<ApiClient["getMapCells"]>(async () =>
    cellsResponse(),
  );
  const getMapTop = vi.fn<ApiClient["getMapTop"]>(async () => topResponse());
  const api = stubClient({ getMapCells, getMapTop, ...client });
  const replaceState = vi.spyOn(window.history, "replaceState");
  render(<MapExplorer initial={initial} client={api} />);
  return { getMapCells, getMapTop, replaceState };
}

const sendViewport = (viewport: Partial<typeof VIEWPORT> = {}) =>
  act(() => map().onViewportChange({ ...VIEWPORT, ...viewport }));

beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: true,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
});

describe("MapExplorer", () => {
  it("loads the best areas for the whole metro without waiting for the map", async () => {
    const { getMapTop, getMapCells } = setup();

    await waitFor(() => expect(getMapTop).toHaveBeenCalled());
    expect(getMapTop).toHaveBeenCalledWith(
      expect.not.objectContaining({ bbox: expect.anything() }),
      expect.anything(),
    );
    expect(getMapCells).not.toHaveBeenCalled();
  });

  it("requests cells for the padded viewport at the coarse precision when zoomed out", async () => {
    const { getMapCells } = setup();

    sendViewport({ zoom: 8 });

    await waitFor(() => expect(getMapCells).toHaveBeenCalled());
    const [query] = getMapCells.mock.calls[0];
    expect(query.precision).toBe(5);
    expect(query.factors).toBeUndefined();
    expect(query.bbox[0]).toBeLessThan(-74.1);
    expect(query.bbox[3]).toBeGreaterThan(40.8);
  });

  it("switches to the fine precision from zoom 10", async () => {
    const { getMapCells } = setup();

    sendViewport({ zoom: 10 });

    await waitFor(() => expect(getMapCells).toHaveBeenCalled());
    expect(getMapCells.mock.calls[0][0]).toMatchObject({ precision: 6 });
  });

  it("refetches cells and best areas with the chosen factors when one is toggled", async () => {
    const user = userEvent.setup();
    const { getMapCells, getMapTop } = setup();
    sendViewport();
    await waitFor(() => expect(getMapCells).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    await waitFor(() => expect(getMapCells).toHaveBeenCalledTimes(2));
    const factors = getMapCells.mock.calls[1][0].factors ?? [];
    expect(factors).toHaveLength(10);
    expect(factors).not.toContain("cafe");
    await waitFor(() => expect(getMapTop).toHaveBeenCalledTimes(2));
    expect(getMapTop.mock.calls[1][0].factors).toEqual(factors);
  });

  it("applies a preset", async () => {
    const user = userEvent.setup();
    const { getMapCells } = setup();
    sendViewport();

    await user.click(screen.getByRole("button", { name: "Commuter" }));

    await waitFor(() =>
      expect(getMapCells).toHaveBeenLastCalledWith(
        expect.objectContaining({ factors: ["transit", "airport", "road"] }),
        expect.anything(),
      ),
    );
  });

  it("learns default weights from the server, then sends importance as absolute weights", async () => {
    const user = userEvent.setup();
    const { getMapCells, getMapTop } = setup();
    sendViewport();
    await waitFor(() => expect(getMapCells).toHaveBeenCalled());
    await screen.findByText("Strongest: Grocery stores 98, Public transit 95", {
      exact: false,
    });

    await user.click(screen.getByText("Adjust importance"));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Public transit" }),
      "high",
    );

    await waitFor(() =>
      expect(getMapTop).toHaveBeenLastCalledWith(
        expect.objectContaining({ weights: { transit: 3 } }),
        expect.anything(),
      ),
    );
    expect(getMapCells).toHaveBeenLastCalledWith(
      expect.objectContaining({ weights: { transit: 3 } }),
      expect.anything(),
    );
  });

  it("restores factors, importance and scope from the URL", async () => {
    const { getMapTop } = setup({
      view: null,
      selection: createSelection(["grocery", "transit"], { transit: "low" }),
      scope: "metro",
    });

    expect(
      screen.getByRole("checkbox", { name: /Grocery stores/ }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Cafes/ })).not.toBeChecked();
    await waitFor(() => expect(getMapTop).toHaveBeenCalled());
    // The default for transit is not known yet, so nothing is overridden on the first request.
    expect(getMapTop.mock.calls[0][0]).toMatchObject({
      factors: ["grocery", "transit"],
    });
    // Once the response reveals it, the stored importance is applied: 1.5 * 0.5.
    await waitFor(() =>
      expect(getMapTop).toHaveBeenLastCalledWith(
        expect.objectContaining({ weights: { transit: 0.75 } }),
        expect.anything(),
      ),
    );
  });

  it("mirrors the view, factors and scope in the URL", async () => {
    const user = userEvent.setup();
    const { replaceState } = setup();
    sendViewport();
    await user.click(screen.getByRole("button", { name: "Family" }));

    await waitFor(() => {
      const url = String(replaceState.mock.calls.at(-1)?.[2]);
      expect(url).toContain("/map?lat=40.7000&lon=-74.0000&z=11");
      expect(url).toContain("factors=grocery%2Cschool");
    });
  });

  it("limits best areas to the viewport on request, and follows only the user's own moves", async () => {
    const user = userEvent.setup();
    const { getMapTop } = setup();
    sendViewport();
    await waitFor(() => expect(getMapTop).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("radio", { name: "This view only" }));

    await waitFor(() => expect(getMapTop).toHaveBeenCalledTimes(2));
    expect(getMapTop.mock.calls[1][0]).toMatchObject({
      bbox: [-74.1, 40.6, -73.9, 40.8],
      minSeparationKm: 1,
    });

    sendViewport({ user: false, bbox: [-73.9, 40.7, -73.8, 40.8] as Bbox });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getMapTop).toHaveBeenCalledTimes(2);

    sendViewport({ user: true, bbox: [-73.9, 40.7, -73.8, 40.8] as Bbox });
    await waitFor(() => expect(getMapTop).toHaveBeenCalledTimes(3));
  });

  it("flies to an entry and opens its popup, then closes it again", async () => {
    const user = userEvent.setup();
    setup();
    const entry = await screen.findByRole("button", { name: /Rank 1/ });

    await user.click(entry);

    expect(map().flyRequest).toMatchObject({ lat: 40.7546, lon: -73.985 });
    expect(map().popup).toMatchObject({ lat: 40.7546, lon: -73.985 });
    expect(map().activeMarkerId).toBe("dr5ru7");
    expect(entry).toHaveAttribute("aria-expanded", "true");

    act(() => map().onPopupClose());
    expect(entry).toHaveAttribute("aria-expanded", "false");
    expect(map().popup).toBeNull();
  });

  it("selects an entry from its marker", async () => {
    setup();
    await screen.findByRole("button", { name: /Rank 1/ });

    act(() => map().onMarkerClick("dr5rxn"));

    expect(screen.getByRole("button", { name: /Rank 2/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(map().markers.map((m) => m.rank)).toEqual([1, 2]);
  });

  it("opens a popup for a clicked cell", async () => {
    setup();

    act(() =>
      map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7, lon: -74 }),
    );

    expect(map().highlightGeohash).toBe("dr5ru7");
    render(<>{map().popup?.children}</>);
    expect(
      screen.getByRole("link", { name: "Full breakdown" }),
    ).toHaveAttribute("href", "/?lat=40.7&lon=-74");
  });

  it("passes every returned cell to the map as a polygon and shows the real range", async () => {
    setup();
    sendViewport();

    await waitFor(() => expect(map().cells.features).toHaveLength(2));
    expect(screen.getByText("In view: 40 to 90")).toBeInTheDocument();
  });

  it("hints to zoom in when the response was truncated", async () => {
    setup(DEFAULT_MAP_STATE, {
      getMapCells: vi.fn(async () => cellsResponse({ truncated: true })),
    });
    sendViewport();

    expect(
      await screen.findByText(/Zoom in for more detail/),
    ).toBeInTheDocument();
  });

  it("says so when no cells are scored in view", async () => {
    setup(DEFAULT_MAP_STATE, {
      getMapCells: vi.fn(async () =>
        cellsResponse({ geohashes: [], scores: [] }),
      ),
    });
    sendViewport();

    expect(
      await screen.findByText("No scored cells in view. Pan or zoom out."),
    ).toBeInTheDocument();
  });

  it("keeps the previous cells on the map while the next request loads", async () => {
    const user = userEvent.setup();
    let release!: (cells: MapCells) => void;
    const getMapCells = vi
      .fn<() => Promise<MapCells>>()
      .mockResolvedValueOnce(cellsResponse())
      .mockImplementationOnce(
        () => new Promise((resolve) => (release = resolve)),
      );
    setup(DEFAULT_MAP_STATE, { getMapCells });
    sendViewport();
    await waitFor(() => expect(map().cells.features).toHaveLength(2));

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    expect(await screen.findByText("Updating scores…")).toBeInTheDocument();
    expect(map().cells.features).toHaveLength(2);
    await act(async () =>
      release(cellsResponse({ geohashes: ["dr5ru"], scores: [10] })),
    );
    await waitFor(() => expect(map().cells.features).toHaveLength(1));
  });

  it("explains a rate limit and offers a retry without dropping the map", async () => {
    const user = userEvent.setup();
    const getMapCells = vi
      .fn<() => Promise<MapCells>>()
      .mockRejectedValueOnce(
        new ApiError("rate-limited", "slow", {
          status: 429,
          retryAfterSeconds: 7,
        }),
      )
      .mockResolvedValueOnce(cellsResponse());
    setup(DEFAULT_MAP_STATE, { getMapCells });
    sendViewport();

    expect(await screen.findByText("Too many requests.")).toBeInTheDocument();
    expect(screen.getByText(/Try again in 7 seconds/)).toBeInTheDocument();
    expect(screen.getByTestId("map")).toBeInTheDocument();

    const notice = screen.getByText("Too many requests.").closest("div")!;
    await user.click(within(notice).getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(map().cells.features).toHaveLength(2));
    expect(screen.queryByText("Too many requests.")).not.toBeInTheDocument();
  });

  it("shows a best-areas error with retry when the API is down", async () => {
    const user = userEvent.setup();
    const getMapTop = vi
      .fn<() => Promise<MapTop>>()
      .mockRejectedValueOnce(new ApiError("network", "down"))
      .mockResolvedValueOnce(topResponse());
    setup(DEFAULT_MAP_STATE, { getMapTop });

    expect(
      await screen.findByText("Can't reach BenriSpace right now.", {
        selector: "strong",
      }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(
      await screen.findByRole("button", { name: /Rank 1/ }),
    ).toBeInTheDocument();
  });

  it("makes no requests and says so when every factor is off", async () => {
    const user = userEvent.setup();
    const { getMapCells, getMapTop } = setup();
    sendViewport();
    await waitFor(() => expect(getMapCells).toHaveBeenCalledTimes(1));
    const topCalls = getMapTop.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Select none" }));

    expect(
      screen.getByText(/Select a factor to color the map/),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("status")
        .some((el) => /No factors selected/.test(el.textContent ?? "")),
    ).toBe(true);
    expect(map().cells.features).toHaveLength(0);
    expect(getMapCells).toHaveBeenCalledTimes(1);
    expect(getMapTop).toHaveBeenCalledTimes(topCalls);
  });

  it("announces the number of best areas politely", async () => {
    setup();
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("status")
          .some((el) => el.textContent === "2 best areas found."),
      ).toBe(true),
    );
  });
});
