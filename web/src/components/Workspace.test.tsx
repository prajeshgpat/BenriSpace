import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import type { AreaGeometry, Bbox, MapCells, MapTop, MapTopResult } from "@/lib/api/types";
import { emptySubScores, jsonResponse, makeAreaBody, liveExplanationBody, liveScoreBody } from "@/test/fixtures";

import type { MapCanvas as MapCanvasType } from "./map/MapCanvas";
import { Workspace } from "./Workspace";

type CanvasProps = Parameters<typeof MapCanvasType>[0];

// A stand-in for Next's router state: pushState and replaceState update the
// search params the way the real integration does, so the page re-renders.
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

// WebGL does not exist in jsdom. The stand-in records the props the page
// passes and lets a test play the part of the map.
const canvas = vi.hoisted(() => ({ props: null as unknown }));
vi.mock("./map/MapCanvas", () => ({
  MapCanvas: (props: unknown) => {
    canvas.props = props;
    return <div data-testid="map" />;
  },
}));
const map = () => canvas.props as CanvasProps;

function setSearch(href: string | URL | null | undefined) {
  const url = String(href ?? "");
  navigation.search = url.includes("?") ? url.slice(url.indexOf("?") + 1) : "";
  act(() => navigation.listeners.forEach((listener) => listener()));
}

let pushState: MockInstance<History["pushState"]>;
let replaceState: MockInstance<History["replaceState"]>;

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

type Responder = (url: string) => Response | Promise<Response>;

const liveApi: Responder = (url) =>
  url.includes("/explanation")
    ? jsonResponse(liveExplanationBody)
    : jsonResponse(liveScoreBody);

const noArea: Responder = () =>
  jsonResponse({ code: "area_not_found", message: "No area" }, 404);

/**
 * The score endpoints speak HTTP to a fetch mock; the map endpoints are
 * stubbed. `/area` has its own mock (404 unless a test says otherwise), so the
 * score-call assertions below count only score and explanation requests.
 */
function setup(
  search = "",
  respond: Responder = liveApi,
  overrides: Partial<ApiClient> = {},
  respondArea: Responder = noArea,
) {
  navigation.search = search;
  const areaMock = vi.fn<typeof fetch>(async (input) => respondArea(String(input)));
  const fetchMock = vi.fn<typeof fetch>(async (input) => respond(String(input)));
  const routed: typeof fetch = (input, init) =>
    String(input).includes("/area?") ? areaMock(input, init) : fetchMock(input, init);
  const getMapCells = vi.fn<ApiClient["getMapCells"]>(async () => cellsResponse());
  const getMapTop = vi.fn<ApiClient["getMapTop"]>(async () => topResponse());
  const client: ApiClient = {
    ...createApiClient({ baseUrl: "http://api.test/v1", fetch: routed }),
    getMapCells,
    getMapTop,
    // No score file: these tests exercise the API path.
    getMapScores: vi.fn(async () => {
      throw new Error("no score file");
    }),
    // No street address unless a test asks for one; the card keeps its coordinates.
    reverseGeocode: vi.fn(async ({ lat, lon }) => ({
      label: null,
      latitude: lat,
      longitude: lon,
    })),
    // The improve card is optional; keep it out of the score-call counts.
    getImprove: vi.fn(async () => {
      throw new Error("improve unavailable");
    }),
    getSimilar: vi.fn(async () => {
      throw new Error("similar unavailable");
    }),
    ...overrides,
  };
  return {
    fetchMock,
    areaMock,
    client,
    getMapCells,
    getMapTop,
    ...render(<Workspace client={client} />),
  };
}

const lookupStatus = () =>
  screen.getAllByRole("status").find((el) => /Scoring|scores \d+ out of/.test(el.textContent ?? ""))!;

const sendViewport = (viewport: Partial<typeof VIEWPORT> = {}) =>
  act(() => map().onViewportChange({ ...VIEWPORT, ...viewport }));

const mapReady = () => screen.findByTestId("map");

const suggestionBody = {
  suggestions: [
    { label: "350 5th Avenue, New York, NY", latitude: 40.7484, longitude: -73.9857 },
    { label: "350 5th Street, Brooklyn, NY", latitude: 40.67, longitude: -73.98 },
  ],
};

beforeEach(() => {
  navigation.search = "";
  // The workspace lives at /app; the history spies below stop it moving.
  window.history.replaceState(null, "", "/app");
  pushState = vi
    .spyOn(window.history, "pushState")
    .mockImplementation((_data, _unused, url) => setSearch(url));
  replaceState = vi
    .spyOn(window.history, "replaceState")
    .mockImplementation((_data, _unused, url) => setSearch(url));
});

describe("Workspace: scoring an address", () => {
  it("shows no welcome text and makes no score request without an address", () => {
    const { fetchMock } = setup("", liveApi);

    expect(screen.queryByText(/click the map to see its score/)).not.toBeInTheDocument();
    expect(screen.queryByText(/within about two hours/)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Enter an address")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /close result/i })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("navigates to a shareable URL when an address is submitted", async () => {
    const user = userEvent.setup();
    setup("", liveApi);

    await user.type(screen.getByRole("combobox", { name: "Address" }), "  350 5th Ave,  New York ");
    await user.click(screen.getByRole("button", { name: "Score" }));

    expect(pushState).toHaveBeenCalledWith(null, "", "/app?address=350+5th+Ave%2C+New+York");
  });

  it("validates before navigating and points the field at the message", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup("", liveApi);

    await user.click(screen.getByRole("button", { name: "Score" }));

    const input = screen.getByRole("combobox", { name: "Address" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an address to score.");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/Enter an address to score\./);
    expect(input).toHaveFocus();
    expect(pushState).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(input, "3");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejects an invalid address arriving via the URL without calling the API", () => {
    const { fetchMock } = setup("address=a", liveApi);

    expect(screen.getByRole("alert")).toHaveTextContent(/at least 3 characters/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads and renders a result from the address in the URL", async () => {
    const { fetchMock } = setup(
      "address=350+5th+Ave%2C+New+York%2C+NY&factors=all",
      liveApi,
    );

    expect(screen.getByTestId("result-skeleton")).toBeInTheDocument();
    expect(lookupStatus()).toHaveTextContent(
      "Scoring 350 5th Ave, New York, NY…",
    );
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue(
      "350 5th Ave, New York, NY",
    );

    expect(
      await screen.findByRole("heading", { level: 2, name: "350 5th Ave, New York, NY" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");
    // Selected filters show their score (or a muted n/a ring); others show none.
    expect(
      screen.getByRole("checkbox", { name: /^Groceries, on, no data/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("factor-ring")).toHaveLength(13);
    expect(screen.queryByText("No data")).not.toBeInTheDocument();
    expect(screen.queryByText("Factor breakdown")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Weights/)).not.toBeInTheDocument();
    expect(screen.queryByText(/grid squares?/)).not.toBeInTheDocument();
    expect(
      await screen.findByText(/strongest factor is airport drive time/),
    ).toBeInTheDocument();
    expect(lookupStatus()).toHaveTextContent(
      "350 5th Ave, New York, NY scores 63 out of 100, Good.",
    );
    expect(document.title).toBe("350 5th Ave, New York, NY · BenriSpace");
    // The score, its explanation, and the travel-time area (the switch starts on).
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reserves the header slot while loading and when loaded, with the filters after it", async () => {
    setup("address=350+5th+Ave%2C+New+York%2C+NY", liveApi);

    const slot = () => screen.getByTestId("result-skeleton").closest("div[class*=headerSlot]");
    const loadingSlot = slot();
    expect(loadingSlot).not.toBeNull();
    const filters = screen.getByRole("heading", { name: "Factors" });
    expect(
      loadingSlot!.compareDocumentPosition(filters) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const score = await screen.findByTestId("composite-score");
    expect(score.closest("div[class*=headerSlot]")).toBe(loadingSlot);
    // Summary comes after the filters, not before.
    const summary = await screen.findByRole("heading", { name: "Summary" });
    expect(
      filters.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the out-of-coverage state for a 404, with no retry", async () => {
    setup("address=1600+Pennsylvania+Ave%2C+Washington+DC", () =>
      jsonResponse({ code: "not_found", message: "No geo entity", upgradeUrl: null }, 404),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That address is outside our coverage");
    expect(alert).toHaveTextContent("1600 Pennsylvania Ave, Washington DC");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("composite-score")).not.toBeInTheDocument();
  });

  it("shows the address-not-found state when geocoding fails", async () => {
    setup("address=zzqqxx", () =>
      jsonResponse({ code: "unresolvable_address", message: "Could not geocode" }, 400),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn't find that address",
    );
  });

  it("shows the network-error state and recovers on retry", async () => {
    const user = userEvent.setup();
    let online = false;
    const { fetchMock } = setup("address=350+5th+Ave", (url) => {
      if (!online) throw new TypeError("Failed to fetch");
      return liveApi(url);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Can't reach BenriSpace right now",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    online = true;
    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(screen.getByTestId("composite-score")).toHaveTextContent("63"),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("re-runs the lookup when the current address is submitted again", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup("address=350+5th+Ave", liveApi);
    await screen.findByText(/strongest factor/);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    await user.click(screen.getByRole("button", { name: "Score" }));

    // A fresh score, its explanation, and the travel-time area drawn again for the new lookup.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
    expect(pushState).not.toHaveBeenCalled();
  });

  it("resyncs the field when the URL address changes underneath it", async () => {
    const { client, rerender } = setup("address=350+5th+Ave", liveApi);
    const input = screen.getByRole("combobox", { name: "Address" });
    expect(input).toHaveValue("350 5th Ave");

    navigation.search = "address=Hoboken+Terminal";
    rerender(<Workspace client={client} />);

    expect(screen.getByRole("combobox", { name: "Address" })).toBe(input);
    expect(input).toHaveValue("Hoboken Terminal");
    await screen.findByRole("heading", { level: 2, name: "Hoboken Terminal" });
  });

  it("does not offer example address chips", () => {
    setup("", liveApi);
    expect(screen.queryByRole("link", { name: "350 5th Ave, New York, NY" })).not.toBeInTheDocument();
    expect(screen.queryByText("Try")).not.toBeInTheDocument();
  });
  describe("autocomplete", () => {
    const withSuggestions: Responder = (url) =>
      url.includes("/suggest") ? jsonResponse(suggestionBody) : liveApi(url);

    it("selecting a suggestion navigates by coordinates, skipping geocoding", async () => {
      const user = userEvent.setup();
      setup("", withSuggestions);
      const input = screen.getByRole("combobox", { name: "Address" });

      await user.type(input, "350 5th");
      const option = await screen.findByRole("option", { name: /350 5th Avenue/ });
      await user.click(option);

      expect(pushState).toHaveBeenCalledWith(
        null,
        "",
        "/app?address=350+5th+Avenue%2C+New+York%2C+NY&lat=40.7484&lon=-73.9857",
      );
      expect(input).toHaveValue("350 5th Avenue, New York, NY");
      expect(screen.queryByRole("option", { name: /5th/ })).not.toBeInTheDocument();
    });

    it("scores a shared coordinate URL without geocoding", async () => {
      const { fetchMock } = setup(
        "address=350+5th+Avenue%2C+New+York%2C+NY&lat=40.7484&lon=-73.9857",
        withSuggestions,
      );

      expect(await screen.findByTestId("composite-score")).toBeInTheDocument();
      const urls = fetchMock.mock.calls.map(([url]) => String(url));
      expect(urls).toContain("http://api.test/v1/score?lat=40.7484&lon=-73.9857");
      expect(urls.some((url) => url.includes("address="))).toBe(false);
      expect(urls.some((url) => url.includes("/suggest"))).toBe(false);
      expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue(
        "350 5th Avenue, New York, NY",
      );
      expect(
        screen.getByRole("heading", { level: 2, name: "350 5th Avenue, New York, NY" }),
      ).toBeInTheDocument();
    });

    it("labels a coordinate-only URL with the coordinates", async () => {
      setup("lat=40.7484&lon=-73.9857", withSuggestions);
      expect(
        await screen.findByRole("heading", { level: 2, name: "40.7484, -73.9857" }),
      ).toBeInTheDocument();
    });

    it("falls back to the address when the coordinates are invalid", async () => {
      const { fetchMock } = setup("address=350+5th+Ave&lat=999&lon=abc", liveApi);
      await screen.findByTestId("composite-score");
      expect(String(fetchMock.mock.calls[0][0])).toContain("/score?address=350+5th+Ave");
    });

    it("still searches typed text with Enter when suggestions fail", async () => {
      const user = userEvent.setup();
      setup("", (url) =>
        url.includes("/suggest")
          ? jsonResponse({ code: "suggest_unavailable", message: "down" }, 503)
          : liveApi(url),
      );
      const input = screen.getByRole("combobox", { name: "Address" });

      await user.type(input, "350 5th Ave");
      await waitFor(() => expect(screen.queryByRole("option", { name: /5th/ })).not.toBeInTheDocument());
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      await user.keyboard("{Enter}");

      expect(pushState).toHaveBeenCalledWith(null, "", "/app?address=350+5th+Ave");
    });

    it("does not look anything up when the field is filled from the URL", async () => {
      const { fetchMock } = setup("address=350+5th+Ave", withSuggestions);
      await screen.findByTestId("composite-score");
      await new Promise((resolve) => setTimeout(resolve, 350));
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/suggest"))).toBe(false);
    });
  });
});

describe("Workspace: the map and its controls", () => {
  it("loads the best areas for the whole metro without waiting for the map", async () => {
    const { getMapTop, getMapCells } = setup();

    await waitFor(() => expect(getMapTop).toHaveBeenCalled());
    expect(getMapTop).toHaveBeenCalledWith(
      expect.not.objectContaining({ bbox: expect.anything() }),
      expect.anything(),
    );
    expect(getMapCells).not.toHaveBeenCalled();
  });

  it("pins the searched place along with a best area when Compare is clicked", async () => {
    const user = userEvent.setup();
    window.sessionStorage.clear();
    setup("address=350+5th+Ave%2C+New+York%2C+NY", liveApi);
    await screen.findByRole("heading", { level: 2, name: "350 5th Ave, New York, NY" });
    const compareButtons = await screen.findAllByRole("button", { name: "Compare: Unnamed area" });
    await user.click(compareButtons[0]);

    const removeButtons = await screen.findAllByRole("button", { name: /^Remove from compare: / });
    const names = removeButtons.map((b) => b.getAttribute("aria-label"));
    expect(names).toHaveLength(2);
    expect(names.some((n) => n?.includes("350 5th Ave"))).toBe(true);
  });

  it("loads the map after the search is on screen", async () => {
    setup();
    expect(screen.getByRole("combobox", { name: "Address" })).toBeInTheDocument();
    expect(await mapReady()).toBeInTheDocument();
  });

  it("requests cells for the padded viewport at the coarse precision when zoomed out", async () => {
    const { getMapCells } = setup("factors=all");
    await mapReady();

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
    await mapReady();

    sendViewport({ zoom: 10 });

    await waitFor(() => expect(getMapCells).toHaveBeenCalled());
    expect(getMapCells.mock.calls[0][0]).toMatchObject({ precision: 6 });
  });

  it("refetches cells and best areas with the chosen factors when one is toggled", async () => {
    const user = userEvent.setup();
    const { getMapCells, getMapTop } = setup("factors=all");
    await mapReady();
    sendViewport();
    await waitFor(() => expect(getMapCells).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    await waitFor(() => expect(getMapCells).toHaveBeenCalledTimes(2));
    const factors = getMapCells.mock.calls[1][0].factors ?? [];
    expect(factors).toHaveLength(12);
    expect(factors).not.toContain("cafe");
    await waitFor(() =>
      expect(getMapTop.mock.lastCall?.[0].factors).toEqual(factors),
    );
  });

  it("sends the chosen factors to the map", async () => {
    const user = userEvent.setup();
    const { getMapCells } = setup();
    await mapReady();
    sendViewport();

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    await waitFor(() =>
      expect(getMapCells).toHaveBeenLastCalledWith(
        expect.objectContaining({ factors: expect.not.arrayContaining(["cafe"]) }),
        expect.anything(),
      ),
    );
  });

  it("learns default weights from the server, then sends importance as absolute weights", async () => {
    const user = userEvent.setup();
    const { getMapCells, getMapTop } = setup();
    await mapReady();
    sendViewport();
    await waitFor(() => expect(getMapCells).toHaveBeenCalled());
    await screen.findByText("Strongest: Groceries 98, Public transit 95", {
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

  it("restores factors and importance from the URL", async () => {
    const { getMapTop } = setup(
      "factors=grocery%2Ctransit&importance=transit%3Alow",
    );

    expect(
      screen.getByRole("checkbox", { name: /Groceries/ }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Cafes/ })).not.toBeChecked();
    await mapReady();
    sendViewport();
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

  it("opens the map on the view in the URL", async () => {
    setup("center=40.75%2C-73.98&z=13");
    await mapReady();
    expect(map().initialView).toEqual({ lat: 40.75, lon: -73.98, zoom: 13 });
  });

  it("opens the map on a scored place from the URL, and marks it", async () => {
    setup("address=x+y+z&lat=40.7484&lon=-73.9857");
    await mapReady();
    expect(map().initialView).toEqual({ lat: 40.7484, lon: -73.9857, zoom: 14 });
    expect(map().pin).toEqual({ lat: 40.7484, lon: -73.9857 });
    // The URL already says where to look, so there is no fly-to on load.
    expect(map().flyRequest).toBeNull();
  });

  it("leaves a pristine URL alone until the view or filters change", async () => {
    setup();
    await mapReady();
    sendViewport({ user: false });

    expect(replaceState).not.toHaveBeenCalled();
  });

  it("mirrors the view and factors in the URL once the user moves the map", async () => {
    const user = userEvent.setup();
    setup();
    await mapReady();
    sendViewport();
    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    await waitFor(() => {
      const url = String(replaceState.mock.calls.at(-1)?.[2]);
      expect(url).toContain("/app?center=40.7000%2C-74.0000&z=11");
      expect(url).toContain("factors=");
      expect(url).not.toContain("cafe");
    });
  });

  it("keeps the scored place in the URL while the map moves", async () => {
    setup("address=Home&lat=40.7484&lon=-73.9857");
    await mapReady();
    sendViewport();

    await waitFor(() => {
      const url = String(replaceState.mock.calls.at(-1)?.[2]);
      expect(url).toContain("address=Home&lat=40.7484&lon=-73.9857");
      expect(url).toContain("center=40.7000%2C-74.0000");
    });
  });

  it("ranks best areas for the view, and follows only the user's own moves", async () => {
    const { getMapTop } = setup();
    await mapReady();
    sendViewport();

    await waitFor(() =>
      expect(getMapTop).toHaveBeenLastCalledWith(
        expect.objectContaining({
          bbox: [-74.1, 40.6, -73.9, 40.8],
          minSeparationMi: 0.6,
        }),
        expect.anything(),
      ),
    );
    const calls = getMapTop.mock.calls.length;

    sendViewport({ user: false, bbox: [-73.9, 40.7, -73.8, 40.8] as Bbox });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getMapTop).toHaveBeenCalledTimes(calls);

    sendViewport({ user: true, bbox: [-73.9, 40.7, -73.8, 40.8] as Bbox });
    await waitFor(() =>
      expect(getMapTop).toHaveBeenLastCalledWith(
        expect.objectContaining({ bbox: [-73.9, 40.7, -73.8, 40.8] }),
        expect.anything(),
      ),
    );
  });

  it("passes every returned cell to the map as a polygon and shows the real range", async () => {
    setup();
    await mapReady();
    sendViewport();

    await waitFor(() => expect(map().cells.features).toHaveLength(2));
    expect(screen.getByText("In view: 40 to 90")).toBeInTheDocument();
  });

  it("hints to zoom in when the response was truncated", async () => {
    setup("", liveApi, {
      getMapCells: vi.fn(async () => cellsResponse({ truncated: true })),
    });
    await mapReady();
    sendViewport();

    expect(
      await screen.findByText(/Zoom in for more detail/),
    ).toBeInTheDocument();
  });

  it("says so when no cells are scored in view", async () => {
    setup("", liveApi, {
      getMapCells: vi.fn(async () =>
        cellsResponse({ geohashes: [], scores: [] }),
      ),
    });
    await mapReady();
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
    setup("", liveApi, { getMapCells });
    await mapReady();
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
    setup("", liveApi, { getMapCells });
    await mapReady();
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
    setup("", liveApi, { getMapTop });

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

  it("makes no map requests and says so when every factor is off", async () => {
    const user = userEvent.setup();
    const { getMapCells, getMapTop } = setup();
    await mapReady();
    sendViewport();
    await waitFor(() => expect(getMapCells).toHaveBeenCalledTimes(1));

    for (const box of screen.getAllByRole("checkbox", { checked: true })) {
      await user.click(box);
    }

    expect(
      screen.getByText(/Select a factor to color the map/),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("status")
        .some((el) => /No factors selected/.test(el.textContent ?? "")),
    ).toBe(true);
    expect(map().cells.features).toHaveLength(0);
    // Turning factors off one by one may fetch on the way; once none are
    // left nothing more is requested.
    const settled = [getMapCells.mock.calls.length, getMapTop.mock.calls.length];
    await new Promise((r) => setTimeout(r, 400));
    expect([getMapCells.mock.calls.length, getMapTop.mock.calls.length]).toEqual(settled);
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

  it("shows the controls and the credits alongside a result", async () => {
    setup("address=350+5th+Ave");
    await screen.findByTestId("composite-score");

    expect(screen.getByRole("heading", { name: "Factors" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Best areas" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "OpenStreetMap contributors" }),
    ).toBeInTheDocument();
  });
});

describe("Workspace: choosing a place on the map", () => {
  it("flies to a searched address and marks it", async () => {
    const user = userEvent.setup();
    setup("", (url) =>
      url.includes("/suggest") ? jsonResponse(suggestionBody) : liveApi(url),
    );
    await mapReady();

    await user.type(screen.getByRole("combobox", { name: "Address" }), "350 5th");
    await user.click(await screen.findByRole("option", { name: /350 5th Avenue/ }));

    await screen.findByTestId("composite-score");
    expect(map().pin).toEqual({ lat: 40.7484, lon: -73.9857 });
    expect(map().flyRequest).toMatchObject({ lat: 40.7484, lon: -73.9857, zoom: 14 });
  });

  it("flies to a typed address once its coordinates are known", async () => {
    const user = userEvent.setup();
    setup("", liveApi);
    await mapReady();

    await user.type(screen.getByRole("combobox", { name: "Address" }), "Grand Central");
    await user.click(screen.getByRole("button", { name: "Score" }));

    await screen.findByTestId("composite-score");
    await waitFor(() => expect(map().flyRequest).not.toBeNull());
    expect(map().flyRequest?.lat).toBeCloseTo(40.7492, 4);
    expect(map().flyRequest?.lon).toBeCloseTo(-73.985, 4);
    expect(map().pin?.lat).toBeCloseTo(40.7492, 4);
  });

  it("scores a best-areas entry in the panel and flies there, then toggles it off", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();
    await mapReady();
    const entry = await screen.findByRole("button", { name: /Rank 1/ });

    await user.click(entry);

    expect(pushState).toHaveBeenCalledWith(
      null,
      "",
      "/app?address=Unnamed+area&lat=40.7546&lon=-73.985",
    );
    expect(await screen.findByTestId("composite-score")).toHaveTextContent("63");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "http://api.test/v1/score?lat=40.7546&lon=-73.985",
    );
    expect(map().flyRequest).toMatchObject({ lat: 40.7546, lon: -73.985 });
    expect(map().activeMarkerId).toBe("dr5ru7");
    expect(map().highlightGeohash).toBe("dr5ru7");
    expect(entry).toHaveAttribute("aria-pressed", "true");

    await user.click(entry);

    expect(screen.queryByTestId("composite-score")).not.toBeInTheDocument();
    expect(entry).toHaveAttribute("aria-pressed", "false");
    expect(map().pin).toBeNull();
  });

  it("selects an entry from its marker", async () => {
    setup();
    await mapReady();
    await screen.findByRole("button", { name: /Rank 1/ });

    act(() => map().onMarkerClick("dr5rxn"));

    expect(screen.getByRole("button", { name: /Rank 2/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(map().markers.map((m) => m.rank)).toEqual([1, 2]);
  });

  it("scores a clicked cell in the panel without moving the map", async () => {
    const { fetchMock } = setup();
    await mapReady();

    act(() =>
      map().onCellClick({
        geohash: "dr5ru7",
        score: 77,
        lat: 40.7000012,
        lon: -74.0000049,
      }),
    );

    expect(pushState).toHaveBeenCalledWith(null, "", "/app?lat=40.7&lon=-74");
    expect(await screen.findByTestId("composite-score")).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "http://api.test/v1/score?lat=40.7&lon=-74",
    );
    expect(map().highlightGeohash).toBe("dr5ru7");
    expect(map().pin).toEqual({ lat: 40.7, lon: -74 });
    expect(map().flyRequest).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: "40.7000, -74.0000" }),
    ).toBeInTheDocument();
  });

  it("shows a street address, not coordinates, for a clicked point", async () => {
    const reverseGeocode = vi.fn<ApiClient["reverseGeocode"]>(
      async ({ lat, lon }) => ({
        label: "14A Rock Street, Jersey City, NJ",
        latitude: lat,
        longitude: lon,
      }),
    );
    setup("", liveApi, { reverseGeocode });
    await mapReady();

    act(() =>
      map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7276, lon: -74.062 }),
    );

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "14A Rock Street, Jersey City, NJ",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Scored for the area around/),
    ).not.toBeInTheDocument();
    expect(reverseGeocode).toHaveBeenCalledWith(
      { lat: 40.7276, lon: -74.062 },
      expect.anything(),
    );
  });

  it("does not look up an address for a typed one", async () => {
    const { client } = setup("address=350+5th+Ave");
    await screen.findByTestId("composite-score");
    expect(client.reverseGeocode).not.toHaveBeenCalled();
  });

  it("leaves the selected score alone when the map filters change", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup("lat=40.7&lon=-74");
    await screen.findByTestId("composite-score");
    await mapReady();
    sendViewport();
    const calls = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));

    await waitFor(() =>
      expect(map().cells.features.length).toBeGreaterThan(0),
    );
    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");
    expect(fetchMock).toHaveBeenCalledTimes(calls);
  });

  it("closes the result and returns to the welcome, keeping the filters", async () => {
    const user = userEvent.setup();
    setup("address=350+5th+Ave&factors=transit");
    await screen.findByTestId("composite-score");

    await user.click(screen.getByRole("button", { name: /close result/i }));

    expect(pushState).toHaveBeenCalledWith(null, "", "/app?factors=transit");
    expect(screen.queryByTestId("composite-score")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Public transit/ })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("");
  });

  it("offers a way back from an error too", async () => {
    const user = userEvent.setup();
    setup("address=zzqqxx", () =>
      jsonResponse({ code: "unresolvable_address", message: "x" }, 400),
    );
    await screen.findByRole("alert");

    await user.click(screen.getByRole("button", { name: /close result/i }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("flies back when the same place is searched again", async () => {
    const user = userEvent.setup();
    setup("address=350+5th+Ave");
    await screen.findByTestId("composite-score");
    await mapReady();
    await waitFor(() => expect(map().flyRequest).not.toBeNull());
    const first = map().flyRequest;

    await user.click(screen.getByRole("button", { name: "Score" }));

    await waitFor(() => expect(map().flyRequest).not.toBe(first));
  });

  it("explains when the map cannot be shown and keeps everything else working", async () => {
    setup();
    await mapReady();

    act(() => map().onUnavailable());

    expect(screen.getByText(/can.t be shown in this browser/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Rank 1/ })).toBeInTheDocument();
  });
});

describe("area polygon", () => {
  const areaApi: Responder = () => jsonResponse(makeAreaBody());

  it("passes the polygon to the map for a clicked point and suppresses nothing else", async () => {
    const { fetchMock, areaMock } = setup("", liveApi, {}, areaApi);
    await mapReady();
    expect(map().areaGeometry ?? null).toBeNull();

    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7, lon: -74 }));

    await waitFor(() => expect(map().areaGeometry).toMatchObject({ type: "Polygon" }));
    expect(screen.queryByText(/Area bounded by/)).not.toBeInTheDocument();
    expect(map().highlightGeohash).toBe("dr5ru7");
    expect(String(areaMock.mock.calls[0][0])).toBe("http://api.test/v1/area?lat=40.7&lon=-74");
    // Only the background AI-explanation upgrade and the travel-time area (the switch
    // starts on) may use the generic fetch.
    expect(
      fetchMock.mock.calls.filter(
        ([url]) =>
          !String(url).includes("/area/explanation?") && !String(url).includes("/isochrone?"),
      ),
    ).toEqual([]);
  });

  it("passes no highlight while the lookup is pending, then the polygon replaces it", async () => {
    let release: (response: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    setup("", liveApi, {}, () => pending);
    await mapReady();

    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7, lon: -74 }));

    expect(map().highlightGeohash).toBeNull();
    expect(map().areaGeometry ?? null).toBeNull();

    await act(async () => release(jsonResponse(makeAreaBody())));
    await waitFor(() => expect(map().areaGeometry).toMatchObject({ type: "Polygon" }));
  });

  it("holds the rectangle back during the fallback lookup and shows it once settled", async () => {
    let release: (response: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    setup("", liveApi, {}, () => pending);
    await mapReady();

    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7, lon: -74 }));
    expect(map().highlightGeohash).toBeNull();

    await act(async () => release(jsonResponse({ code: "area_not_found", message: "No area" }, 404)));
    expect(await screen.findByTestId("composite-score")).toBeInTheDocument();
    expect(map().areaGeometry ?? null).toBeNull();
    expect(map().highlightGeohash).toBe("dr5ru7");
  });

  it("falls back to the rectangle when there is no area", async () => {
    setup();
    await mapReady();

    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7, lon: -74 }));

    expect(await screen.findByTestId("composite-score")).toBeInTheDocument();
    expect(map().areaGeometry ?? null).toBeNull();
    expect(map().highlightGeohash).toBe("dr5ru7");
    expect(screen.queryByTestId("area-note")).not.toBeInTheDocument();
  });

  it("re-resolves the area for a shared coordinates URL", async () => {
    setup("lat=40.7&lon=-74", liveApi, {}, areaApi);
    await waitFor(() => expect(map().areaGeometry).toMatchObject({ type: "Polygon" }));
  });

  it("shows the road polygon, not the rectangle, for a best-areas pick", async () => {
    const user = userEvent.setup();
    const { areaMock } = setup("", liveApi, {}, areaApi);
    await mapReady();

    await user.click(await screen.findByRole("button", { name: /Rank 1/ }));

    await waitFor(() => expect(map().areaGeometry).toMatchObject({ type: "Polygon" }));
    expect(areaMock).toHaveBeenCalled();
  });

  it("falls back to the rectangle when the area is not found", async () => {
    const user = userEvent.setup();
    setup("", liveApi, {}, noArea);
    await mapReady();

    await user.click(await screen.findByRole("button", { name: /Rank 1/ }));

    expect(await screen.findByTestId("composite-score")).toBeInTheDocument();
    await waitFor(() => expect(map().highlightGeohash).toBe("dr5ru7"));
    expect(map().areaGeometry ?? null).toBeNull();
  });

  it("clears the polygon when the result is closed", async () => {
    const user = userEvent.setup();
    setup("lat=40.7&lon=-74", liveApi, {}, areaApi);
    await waitFor(() => expect(map().areaGeometry).toMatchObject({ type: "Polygon" }));

    await user.click(screen.getByRole("button", { name: "Close result" }));

    expect(map().areaGeometry ?? null).toBeNull();
  });
});

describe("selection reaches the point endpoints", () => {
  const improveBody = { composite: 60, radiusMi: 1, suggestions: [], bestNearby: null, priorities: [] };
  const similarBody = {
    minSeparationMi: 1,
    priorities: [],
    results: [
      {
        latitude: 40.8,
        longitude: -74,
        direction: "N",
        distanceLabel: "3 mi",
        similarity: 90,
        compositeScore: 70,
        areaLabel: "Area bounded by Test Rd",
        differences: [{ factor: "transit" as const, label: "transit", delta: 8 }],
        summary: "",
      },
    ],
  };

  function setupPoint() {
    const getImprove = vi.fn<ApiClient["getImprove"]>(async () => improveBody);
    const getSimilar = vi.fn<ApiClient["getSimilar"]>(async () => similarBody);
    const getAreaExplanation = vi.fn<ApiClient["getAreaExplanation"]>(async () => ({
      explanation: "AI text.",
      source: "ai",
      areaId: 1,
      priorities: [],
    }));
    const rendered = setup(
      "lat=40.7&lon=-74&factors=all",
      liveApi,
      { getImprove, getSimilar, getAreaExplanation },
      () => jsonResponse(makeAreaBody()),
    );
    return { getImprove, getSimilar, getAreaExplanation, ...rendered };
  }

  it("omits factors while all are selected, then sends the narrowed list once", async () => {
    const user = userEvent.setup();
    const { getImprove, getSimilar, getAreaExplanation } = setupPoint();

    expect(await screen.findByText("Similar areas")).toBeInTheDocument();
    await waitFor(() => expect(getAreaExplanation).toHaveBeenCalledTimes(1));
    for (const call of [getImprove.mock.calls[0], getSimilar.mock.calls[0], getAreaExplanation.mock.calls[0]]) {
      expect((call[2] as { factors?: unknown }).factors).toBeUndefined();
    }
    expect(screen.getByRole("button", { name: "Show similar area 1 on map" })).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /Cafes/ }));
    await user.click(screen.getByRole("checkbox", { name: /Gym/ }));

    await waitFor(() => expect(getSimilar).toHaveBeenCalledTimes(2), { timeout: 2000 });
    expect(getSimilar.mock.calls[1][2]).toMatchObject({
      factors: expect.not.arrayContaining(["cafe", "gym"]),
    });
    expect((getSimilar.mock.calls[1][2] as { factors: string[] }).factors).toHaveLength(11);
    await waitFor(() => expect(getImprove).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getAreaExplanation).toHaveBeenCalledTimes(2));
    expect(getImprove.mock.calls[1][2]).toMatchObject({ factors: expect.any(Array) });
    expect((getAreaExplanation.mock.calls[1][2] as { factors: string[] }).factors).toHaveLength(11);
    // Two toggles, one request each.
    expect(getSimilar).toHaveBeenCalledTimes(2);
  });
});

describe("Workspace: points of interest", () => {
  const park = { label: "Park Ave, NY", latitude: 40.75, longitude: -73.97 };

  it("Score looks up typed points of interest first, then scores the main address", async () => {
    const user = userEvent.setup();
    const suggestAddresses = vi.fn<ApiClient["suggestAddresses"]>(async () => [park]);
    setup("", liveApi, { suggestAddresses });

    await user.type(screen.getByRole("combobox", { name: "Address" }), "350 5th Ave, New York");
    await user.click(screen.getByRole("button", { name: "Point of interest" }));
    await user.type(
      screen.getByRole("combobox", { name: "Point of interest 1 address" }),
      "park ave",
    );
    suggestAddresses.mockClear();
    await user.click(screen.getByRole("button", { name: "Score" }));

    expect(suggestAddresses).toHaveBeenCalledWith("park ave", { limit: 1 });
    await waitFor(() =>
      expect(pushState).toHaveBeenCalledWith(null, "", expect.stringContaining("address=350+5th+Ave")),
    );
    expect(screen.getByRole("combobox", { name: "Point of interest 1 address" })).toHaveValue(
      "Park Ave, NY",
    );
    // The resolved point is in the shared link.
    await waitFor(() =>
      expect(replaceState).toHaveBeenCalledWith(null, "", expect.stringContaining("pt=40.75000%2C-73.97000")),
    );
  });

  it("a map tap fills the selected point-of-interest box instead of scoring the place", async () => {
    const user = userEvent.setup();
    const reverseGeocode = vi.fn<ApiClient["reverseGeocode"]>(async ({ lat, lon }) => ({
      label: "Tapped Plaza, NY",
      latitude: lat,
      longitude: lon,
    }));
    setup("address=350+5th+Ave%2C+New+York%2C+NY", liveApi, { reverseGeocode });
    await screen.findByText(/strongest factor/);
    await user.click(screen.getByRole("button", { name: "Point of interest" }));
    const box = screen.getByRole("combobox", { name: "Point of interest 1 address" });
    // The new box is armed ("Drop a pin") and the keyboard stays closed.
    expect(box).not.toHaveFocus();
    expect(box).toHaveAttribute("placeholder", "Drop a pin");
    pushState.mockClear();

    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7411, lon: -73.9897 }));

    await waitFor(() => expect(box).toHaveValue("Tapped Plaza, NY"));
    expect(pushState).not.toHaveBeenCalled(); // the tapped place was not scored as the main one
    expect(box).toHaveAttribute("placeholder", "Point of interest 1");

    // Filling disarms the box: the next tap scores the place as before.
    act(() => map().onCellClick({ geohash: "dr5ru8", score: 77, lat: 40.76, lon: -73.98 }));
    await waitFor(() => expect(pushState).toHaveBeenCalled());
  });

  it("pressing elsewhere in the sheet disarms the box", async () => {
    const user = userEvent.setup();
    setup("address=350+5th+Ave%2C+New+York%2C+NY", liveApi);
    await screen.findByText(/strongest factor/);
    await user.click(screen.getByRole("button", { name: "Point of interest" }));
    const box = screen.getByRole("combobox", { name: "Point of interest 1 address" });
    expect(box).toHaveAttribute("placeholder", "Drop a pin");
    await user.click(screen.getByRole("heading", { name: "Factors" }));
    expect(box).toHaveAttribute("placeholder", "Point of interest 1");
    pushState.mockClear();
    act(() => map().onCellClick({ geohash: "dr5ru7", score: 77, lat: 40.7411, lon: -73.9897 }));
    await waitFor(() => expect(pushState).toHaveBeenCalled());
  });

  describe("with a point of interest placed", () => {
    const polygon: AreaGeometry = {
      type: "Polygon",
      coordinates: [[[-74, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74, 40.7]]],
    };
    const iso = {
      label: null,
      mode: "transit" as const,
      minutes: 20,
      method: "network" as const,
      areaSqMi: 1,
      cellCount: 3,
      geometry: polygon,
    };
    const triangulate = vi.fn<ApiClient["triangulate"]>(async () => ({
      results: [
        { lat: 40.71, lon: -73.99, score: 81.4, address: "1 Main St" },
        { lat: 40.8, lon: -73.9, score: 70, address: "2 Side St" },
      ],
      isochrones: [iso, iso],
      combined: iso,
    }));
    const withPoint = () =>
      setup("address=350+5th+Ave%2C+New+York%2C+NY&pt=40.75%2C-73.97", liveApi, { triangulate });

    it("hides the score card and suggestions, keeping the overlap results", async () => {
      withPoint();
      await screen.findByRole("heading", { name: "Best areas in the overlap" });
      expect(screen.queryByRole("region", { name: "Selected location" })).toBeNull();
      expect(screen.queryByTestId("composite-score")).toBeNull();
      expect(screen.queryByRole("heading", { name: "Best areas" })).toBeNull();
      expect(map().areaGeometry).toBeNull();
      // The searched place stays in the search box and on the map.
      expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("350 5th Ave, New York, NY");
      expect(map().pin).not.toBeNull();
      expect(screen.getByRole("group", { name: "Travel areas legend" })).toBeInTheDocument();
    });

    it("draws the overlap best areas as the map's ranked markers", async () => {
      withPoint();
      await screen.findByRole("heading", { name: "Best areas in the overlap" });
      expect(map().areaGeometry).toBeNull();
      expect(map().highlightGeohash).toBeNull();
      expect(map().markers.map((m) => [m.id, m.rank, m.tooltip])).toEqual([
        ["overlap:40.71,-73.99", 1, "1 Main St \u00b7 81"],
        ["overlap:40.8,-73.9", 2, "2 Side St \u00b7 70"],
      ]);
    });

    it("labels the legend POI Overlap with no numbered point rows", async () => {
      withPoint();
      await screen.findByRole("heading", { name: "Best areas in the overlap" });
      const legend = screen.getByRole("group", { name: "Travel areas legend" });
      expect(legend).toHaveTextContent("POI Overlap");
      expect(legend).not.toHaveTextContent("Point of interest");
    });

    it("keeps the main address boundary while a point row is added but has no place", async () => {
      const user = userEvent.setup();
      setup("address=350+5th+Ave%2C+New+York%2C+NY", liveApi);
      await screen.findByRole("region", { name: "Selected location" });
      const before = map().areaGeometry;
      await user.click(screen.getByRole("button", { name: "Point of interest" }));
      expect(map().triangulation).toBeNull();
      expect(map().areaGeometry).toBe(before);
    });

    describe("picking an area in the overlap", () => {
      const pickedScore = {
        ...liveScoreBody,
        compositeScore: 66,
        subScores: { ...emptySubScores, grocery: 11, transit: 22, cafe: 33 },
      };
      const pickClient = createApiClient({
        baseUrl: "http://api.test/v1",
        fetch: async () => jsonResponse(pickedScore),
      });
      const withPick = () =>
        setup("address=350+5th+Ave%2C+New+York%2C+NY&pt=40.75%2C-73.97", liveApi, {
          triangulate,
          getScoreByCoordinates: vi.fn<ApiClient["getScoreByCoordinates"]>(async (c) =>
            pickClient.getScoreByCoordinates(c),
          ),
        });

      function expectPicked(search: string) {
        expect(screen.queryByText("Score this area")).toBeNull();
        expect(screen.queryByRole("region", { name: "Previewed area" })).toBeNull();
        expect(window.location.search).toBe(search);
        expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue(
          "350 5th Ave, New York, NY",
        );
        expect(map().previewPin).toBeNull();
        expect(map().activeMarkerId).toBe("overlap:40.71,-73.99");
        expect(map().flyRequest).toMatchObject({ lat: 40.71, lon: -73.99 });
        expect(map().flyRequest?.zoom).toBeUndefined();
      }

      it("opens a score card above the results when a row is clicked", async () => {
        const user = userEvent.setup();
        withPick();
        const heading = await screen.findByRole("heading", { name: "Best areas in the overlap" });
        const search = window.location.search;
        pushState.mockClear();
        await user.click(screen.getByRole("button", { name: /1 Main St/ }));

        const card = await screen.findByRole("region", { name: "Area in the overlap" });
        expect(
          card.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
        expect(await within(card).findByTestId("composite-score")).toBeInTheDocument();
        expect(within(card).getByText("1 Main St")).toBeInTheDocument();
        expect(within(card).queryByRole("button", { name: /copy/i })).toBeNull();
        expectPicked(search);
        expect(pushState).not.toHaveBeenCalled();
        expect(screen.getByRole("button", { name: /1 Main St/ })).toHaveAttribute(
          "aria-pressed",
          "true",
        );
      });

      it("does the same from the map marker, and Factors show the area's sub-scores", async () => {
        withPick();
        await screen.findByRole("heading", { name: "Best areas in the overlap" });
        const search = window.location.search;
        const mainGrocery = screen.getByRole("checkbox", { name: /^Groceries, on, no data/ });
        expect(mainGrocery).toBeInTheDocument();
        act(() => map().onMarkerClick("overlap:40.71,-73.99"));
        const card = await screen.findByRole("region", { name: "Area in the overlap" });
        await within(card).findByTestId("composite-score");
        expectPicked(search);
        expect(
          screen.getByRole("checkbox", { name: "Groceries, on, scored 11 out of 100" }),
        ).toBeInTheDocument();

        await userEvent.setup().click(
          within(card).getByRole("button", { name: "Close area in the overlap" }),
        );
        expect(screen.queryByRole("region", { name: "Area in the overlap" })).toBeNull();
        expect(map().activeMarkerId).toBeNull();
        expect(screen.getByRole("checkbox", { name: /^Groceries, on, no data/ })).toBeInTheDocument();
      });
    });

    it("brings the score card back once the last point is removed", async () => {
      const user = userEvent.setup();
      withPoint();
      await screen.findByRole("heading", { name: "Best areas in the overlap" });
      await user.click(screen.getByRole("button", { name: "Remove point of interest 1" }));
      expect(await screen.findByRole("region", { name: "Selected location" })).toBeInTheDocument();
      expect(screen.queryByRole("group", { name: "Travel areas legend" })).toBeNull();
    });

    it("keeps the score card and the searched place's travel area, and says so, when nothing overlaps", async () => {
      const empty = vi.fn<ApiClient["triangulate"]>(async () => ({
        results: [],
        isochrones: [iso, iso],
        combined: { ...iso, cellCount: 0 },
      }));
      setup("address=350+5th+Ave%2C+New+York%2C+NY&pt=40.75%2C-73.97", liveApi, { triangulate: empty });
      expect((await screen.findAllByText(/travel areas don't overlap/)).length).toBeGreaterThan(0);
      expect(screen.getByRole("region", { name: "Selected location" })).toBeInTheDocument();
      expect(map().triangulation?.anchors.find((a) => a.index === 0)?.geometry).not.toBeNull();
    });
  });

  it("puts Ask Benri directly below the score card", async () => {
    setup("address=350+5th+Ave%2C+New+York%2C+NY", liveApi);
    const card = await screen.findByRole("region", { name: "Selected location" });
    const ask = screen.getByRole("button", { name: "Ask Benri" });
    expect(card.compareDocumentPosition(ask) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const pill = screen.getByRole("button", { name: "Point of interest" });
    expect(pill.compareDocumentPosition(ask) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const factors = screen.getByRole("group", { name: "Travel time" });
    expect(ask.compareDocumentPosition(factors) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
