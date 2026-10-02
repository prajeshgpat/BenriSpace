import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, useSyncExternalStore } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createApiClient, type ApiClient } from "@/lib/api/client";
import { jsonResponse, liveExplanationBody, liveScoreBody } from "@/test/fixtures";

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

function setSearch(href: string | URL | null | undefined) {
  const url = String(href ?? "");
  navigation.search = url.includes("?") ? url.slice(url.indexOf("?") + 1) : "";
  act(() => navigation.listeners.forEach((listener) => listener()));
}

type GetCurrentPosition = Geolocation["getCurrentPosition"];

const MANHATTAN = { latitude: 40.74918, longitude: -73.98503 };
const BOSTON = { latitude: 42.3601, longitude: -71.0589 };
const KANSAS = { latitude: 39.0997, longitude: -94.5786 };

let getCurrentPosition: ReturnType<typeof vi.fn<GetCurrentPosition>>;

function installGeolocation(impl?: GetCurrentPosition) {
  getCurrentPosition = vi.fn<GetCurrentPosition>(impl);
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { getCurrentPosition },
  });
}

const positionAt =
  (coords: { latitude: number; longitude: number }): GetCurrentPosition =>
  (success) =>
    success({ coords, timestamp: 0 } as GeolocationPosition);

const failWith =
  (code: number): GetCurrentPosition =>
  (_success, error) =>
    error?.({ code, message: "" } as GeolocationPositionError);

function setSecureContext(value: boolean) {
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value,
  });
}

function setup(search = "", respond?: (url: string) => Response) {
  navigation.search = search;
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (respond) return respond(url);
    return url.includes("/explanation")
      ? jsonResponse(liveExplanationBody)
      : jsonResponse(liveScoreBody);
  });
  const client: ApiClient = {
    ...createApiClient({ baseUrl: "http://api.test/v1", fetch: fetchMock }),
    getMapCells: vi.fn(async () => ({
      precision: 5 as const,
      factors: [],
      weights: {},
      weightsVersion: "v1",
      truncated: false,
      geohashes: [],
      scores: [],
    })),
    getMapTop: vi.fn(async () => ({
      factors: [],
      weights: {},
      weightsVersion: "v1",
      results: [],
    })),
  } as unknown as ApiClient;
  render(<Workspace client={client} />);
  return { fetchMock };
}

const locateButtons = () =>
  screen.getAllByRole("button", { name: /use my current location|locating/i });
/** The button inside the search box, on its right edge. */
const panelButton = () =>
  locateButtons().find((el) => screen.getByRole("search").contains(el))!;
const mapButton = () =>
  locateButtons().find((el) => !screen.getByRole("search").contains(el))!;
const scoreCalls = (fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes("/score?"));

let pushState: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  setSecureContext(true);
  installGeolocation(positionAt(MANHATTAN));
  navigation.search = "";
  window.history.replaceState(null, "", "/app");
  pushState = vi
    .spyOn(window.history, "pushState")
    .mockImplementation((_d, _u, url) => setSearch(url));
  vi.spyOn(window.history, "replaceState").mockImplementation((_d, _u, url) =>
    setSearch(url),
  );
});

afterEach(() => {
  Reflect.deleteProperty(navigator, "geolocation");
  Reflect.deleteProperty(window, "isSecureContext");
});

describe("Workspace: use my current location", () => {
  it("never asks for the position on load, with or without a result URL", async () => {
    setup();
    setup("address=Your+location&lat=40.7492&lon=-73.985");
    await screen.findAllByTestId("map");
    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it("offers a named button inside the search box and another on the map", () => {
    setup();
    expect(panelButton()).toHaveAccessibleName("Use my current location");
    expect(panelButton()).toHaveAttribute("type", "button");
    expect(mapButton()).toHaveAccessibleName("Use my current location");
  });

  it("selects the position like a chosen suggestion", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.click(panelButton());

    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(getCurrentPosition.mock.calls[0][2]).toEqual({
      enableHighAccuracy: false,
      timeout: 10_000,
      maximumAge: 60_000,
    });
    await waitFor(() =>
      expect(pushState).toHaveBeenCalledWith(
        null,
        "",
        "/app?address=Your+location&lat=40.7492&lon=-73.985",
      ),
    );
    expect(
      await screen.findByRole("heading", { level: 2, name: "Your location" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toBeInTheDocument();
    expect(map().pin).toEqual({ lat: 40.7492, lon: -73.985 });
    await waitFor(() =>
      expect(map().flyRequest).toMatchObject({ lat: 40.7492, lon: -73.985 }),
    );
    const sent = scoreCalls(fetchMock).map(([url]) => String(url));
    expect(sent.every((url) => url.includes("lat=40.7492&lon=-73.985"))).toBe(true);
  });

  it("works from the map button too", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(mapButton());
    expect(
      await screen.findByRole("heading", { level: 2, name: "Your location" }),
    ).toBeInTheDocument();
  });

  it("shows a busy, disabled button while waiting for the position", async () => {
    const user = userEvent.setup();
    let resolve!: () => void;
    installGeolocation((success) => {
      resolve = () => positionAt(MANHATTAN)(success, () => {});
    });
    setup();

    await user.click(panelButton());

    const button = panelButton();
    expect(button).toHaveAccessibleName("Locating…");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(mapButton()).toBeDisabled();

    act(() => resolve());
    await waitFor(() => expect(panelButton()).toBeEnabled());
    expect(panelButton()).toHaveAccessibleName("Use my current location");
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
  });

  it.each([
    [1, /blocked for this site.*type an address instead/i],
    [2, /couldn't work out where you are/i],
    [3, /took too long/i],
  ])("explains geolocation error %i and allows a retry", async (code, message) => {
    const user = userEvent.setup();
    installGeolocation(failWith(code));
    setup();

    await user.click(panelButton());

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(panelButton()).toBeEnabled();
    expect(pushState).not.toHaveBeenCalled();

    installGeolocation(positionAt(MANHATTAN));
    await user.click(panelButton());
    expect(
      await screen.findByRole("heading", { level: 2, name: "Your location" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(message)).not.toBeInTheDocument();
  });

  it("announces errors in a live region", async () => {
    const user = userEvent.setup();
    installGeolocation(failWith(1));
    setup();
    await user.click(panelButton());
    const text = await screen.findByText(/blocked for this site/);
    expect(text.closest("[aria-live]")).toHaveAttribute("aria-live", "assertive");
  });

  it.each([
    ["Boston", BOSTON],
    ["Kansas", KANSAS],
  ])("says so for a position in %s and leaves the map alone", async (_name, place) => {
    const user = userEvent.setup();
    installGeolocation(positionAt(place));
    const { fetchMock } = setup();

    await user.click(panelButton());

    expect(
      await screen.findByText(/outside the area BenriSpace covers — the NYC metro/),
    ).toBeInTheDocument();
    expect(pushState).not.toHaveBeenCalled();
    expect(map().flyRequest).toBeNull();
    expect(map().pin).toBeNull();
    expect(scoreCalls(fetchMock)).toHaveLength(0);
  });

  it("also treats a 404 from the API inside the bounds as out of coverage", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup("", () =>
      jsonResponse({ code: "not_found", message: "none", upgradeUrl: null }, 404),
    );

    await user.click(panelButton());

    expect(await screen.findByText(/outside the area BenriSpace covers/)).toBeInTheDocument();
    expect(scoreCalls(fetchMock)).toHaveLength(1);
    expect(pushState).not.toHaveBeenCalled();
    expect(map().flyRequest).toBeNull();
  });

  it("disables the button with a reason when the browser has no geolocation", () => {
    Reflect.deleteProperty(navigator, "geolocation");
    setup();

    const button = panelButton();
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(/can't share your location/);
    expect(screen.queryAllByRole("button", { name: /use my current location/i })).toHaveLength(1);
  });

  it("disables the button with a reason on an insecure page", () => {
    setSecureContext(false);
    setup();

    expect(panelButton()).toBeDisabled();
    expect(panelButton()).toHaveAccessibleDescription(/secure \(https\) connection/);
    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it("keeps the rest of the page working after a failure", async () => {
    const user = userEvent.setup();
    installGeolocation(failWith(1));
    setup();
    await user.click(panelButton());
    await screen.findByText(/blocked for this site/);

    await user.type(screen.getByRole("combobox", { name: "Address" }), "350 5th Ave");
    await user.click(screen.getByRole("button", { name: "Get score" }));
    expect(pushState).toHaveBeenCalledWith(null, "", "/app?address=350+5th+Ave");
    expect(within(document.body).getByTestId("map")).toBeInTheDocument();
  });
});
