import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createApiClient, type ApiClient } from "@/lib/api/client";
import type { ChatReply } from "@/lib/api/types";
import {
  jsonResponse,
  liveExplanationBody,
  liveScoreBody,
  makeAreaScore,
} from "@/test/fixtures";

import type { MapCanvas as MapCanvasType } from "./map/MapCanvas";
import { Workspace } from "./Workspace";
import { DEFAULT_FACTOR_KEYS } from "@/lib/map/selection";

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

const REPLY: ChatReply = {
  reply: "Darien looks best.",
  results: [
    { label: "Darien, CT", latitude: 41.07, longitude: -73.47, score: 87, weeklyMinutes: 274, why: "Short trips." },
  ],
  sources: [],
  limited: false,
};

function setup(
  search = "address=350+5th+Ave&lat=40.7484&lon=-73.9857",
  overrides: Partial<ApiClient> = {},
) {
  navigation.search = search;
  const fetchMock = vi.fn<typeof fetch>(async (input) =>
    String(input).includes("/explanation")
      ? jsonResponse(liveExplanationBody)
      : jsonResponse(liveScoreBody),
  );
  const chat = vi.fn<ApiClient["chat"]>(async () => REPLY);
  const client: ApiClient = {
    ...createApiClient({ baseUrl: "http://api.test/v1", fetch: fetchMock }),
    chat,
    getAreaByCoordinates: vi.fn(async () => makeAreaScore()),
    getMapCells: vi.fn(async () => ({
      precision: 5, factors: [], weights: {}, weightsVersion: "v1",
      truncated: false, geohashes: [], scores: [],
    })) as unknown as ApiClient["getMapCells"],
    getMapTop: vi.fn(async () => ({
      factors: [], weights: {}, weightsVersion: "v1", results: [],
    })) as unknown as ApiClient["getMapTop"],
    reverseGeocode: vi.fn(async ({ lat, lon }) => ({
      label: lat === 40.7492 ? "350 5th Avenue, New York, NY" : null,
      latitude: lat,
      longitude: lon,
    })),
    getImprove: vi.fn(async () => { throw new Error("improve unavailable"); }),
    getSimilar: vi.fn(async () => { throw new Error("similar unavailable"); }),
    ...overrides,
  };
  render(<Workspace client={client} />);
  return { chat };
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/app");
  vi.spyOn(window.history, "pushState").mockImplementation((_d, _u, url) => {
    const text = String(url ?? "");
    navigation.search = text.includes("?") ? text.slice(text.indexOf("?") + 1) : "";
    act(() => navigation.listeners.forEach((l) => l()));
  });
  vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
});

describe("Workspace: Ask Benri", () => {
  it("opens the chat inline in place of the button, with live place and filter context", async () => {
    const user = userEvent.setup();
    const { chat } = setup();
    await screen.findByTestId("composite-score");

    await user.click(screen.getByRole("button", { name: "Ask Benri" }));

    // The button became the chat, in the same place (before the result card).
    expect(screen.queryByRole("button", { name: "Ask Benri" })).not.toBeInTheDocument();
    const region = await screen.findByRole("region", { name: "Ask Benri" });
    expect(
      region.compareDocumentPosition(screen.getByTestId("composite-score")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByRole("log", { name: "Conversation" })).toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveFocus();

    await user.type(screen.getByRole("textbox", { name: "Your question" }), "best nearby?{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).toMatchObject({
      address: "350 5th Ave",
      latitude: 40.7484,
      longitude: -73.9857,
    });

    // Changing the place while chatting is noted and used by the next question.
    act(() => {
      window.history.pushState(null, "", "/app?lat=40.67&lon=-73.98&address=Park+Slope");
    });
    expect(await screen.findByText(/^Now looking at/)).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "and now?{Enter}");
    await waitFor(() => expect(chat).toHaveBeenCalledTimes(2));
    expect(chat.mock.calls[1][1]).toMatchObject({ latitude: 40.67, longitude: -73.98 });

    await user.click(screen.getByRole("button", { name: "Close chat" }));
    expect(screen.getByRole("button", { name: "Ask Benri" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ask Benri" })).not.toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toBeInTheDocument();
  });

  it("sends the overlap, and leads with a question about it, when points of interest are placed", async () => {
    const user = userEvent.setup();
    const iso = {
      label: null, mode: "transit" as const, minutes: 20, method: "network" as const,
      areaSqMi: 1, cellCount: 3, geometry: null,
    };
    const { chat } = setup("address=350+5th+Ave&lat=40.7484&lon=-73.9857&pt=40.75%2C-73.97", {
      triangulate: vi.fn(async () => ({
        results: [{ lat: 40.71, lon: -73.99, score: 81.4, address: "1 Main St" }],
        isochrones: [iso, iso],
        combined: iso,
      })),
    });
    await screen.findByRole("heading", { name: "Best areas in the overlap" });
    await user.click(screen.getByRole("button", { name: "Ask Benri" }));
    expect(
      await screen.findByRole("button", { name: "What are the pros and cons of the areas in the overlap?" }),
    ).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Your question" }), "which is best?{Enter}");
    await screen.findByText("Darien looks best.");
    const trip = (chat.mock.calls[0][1] as { trip?: unknown }).trip as {
      places: { label: string; mode: string; minutes: number }[];
      areas: { label: string; score: number }[];
      overlap: boolean;
    };
    expect(trip.places.map((p) => [p.mode, p.minutes])).toHaveLength(2);
    expect(trip.places[0].label).toBeTruthy();
    expect(trip.areas).toEqual([
      { label: "1 Main St", latitude: 40.71, longitude: -73.99, score: 81 },
    ]);
    expect(trip.overlap).toBe(true);
  });

  describe("a reply with a plan", () => {
    const PLAN_REPLY: ChatReply = {
      ...REPLY,
      plan: {
        place: { label: "Work, Stamford", latitude: 41.05, longitude: -73.54 },
        points: [
          { label: "Planet Fitness", latitude: 41.06, longitude: -73.53 },
          { label: "Whole Foods", latitude: 41.04, longitude: -73.55 },
        ],
      },
    };
    const triangulate = vi.fn(async () => ({
      results: [],
      isochrones: [],
      combined: null,
    })) as unknown as ApiClient["triangulate"];

    it("puts the points in the planner with their labels and moves the searched place", async () => {
      const user = userEvent.setup();
      const reverseGeocode = vi.fn(async ({ lat, lon }: { lat: number; lon: number }) => ({
        label: null,
        latitude: lat,
        longitude: lon,
      }));
      const { chat } = setup(undefined, {
        chat: vi.fn(async () => PLAN_REPLY),
        triangulate,
        reverseGeocode,
      });
      void chat;
      await screen.findByTestId("composite-score");
      await user.click(screen.getByRole("button", { name: "Ask Benri" }));
      await user.type(screen.getByRole("textbox", { name: "Your question" }), "near work{Enter}");

      expect(await screen.findByRole("combobox", { name: "Point of interest 1 address" })).toHaveValue(
        "Planet Fitness",
      );
      expect(screen.getByRole("combobox", { name: "Point of interest 2 address" })).toHaveValue(
        "Whole Foods",
      );
      // Labels were given, so no address lookup for the points.
      expect(reverseGeocode).not.toHaveBeenCalledWith({ lat: 41.06, lon: -73.53 });
      expect(reverseGeocode).not.toHaveBeenCalledWith({ lat: 41.04, lon: -73.55 });
      expect(navigation.search).toContain("lat=41.05");
      expect(navigation.search).toContain("lon=-73.54");
      expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("Work, Stamford");
      expect(screen.getByRole("region", { name: "Ask Benri" })).toBeInTheDocument();
    });

    it("keeps the searched place when the plan's place is where it already is", async () => {
      const user = userEvent.setup();
      setup(undefined, {
        chat: vi.fn(async () => ({
          ...PLAN_REPLY,
          plan: { ...PLAN_REPLY.plan!, place: { label: "Same", latitude: 40.7485, longitude: -73.9857 } },
        })),
        triangulate,
      });
      await screen.findByTestId("composite-score");
      await user.click(screen.getByRole("button", { name: "Ask Benri" }));
      await user.type(screen.getByRole("textbox", { name: "Your question" }), "near here{Enter}");

      await screen.findByRole("combobox", { name: "Point of interest 1 address" });
      expect(window.history.pushState).not.toHaveBeenCalled();
      expect(navigation.search).toContain("lat=40.7484");
    });
  });

  it("does not send a trip without points of interest", async () => {
    const user = userEvent.setup();
    const { chat } = setup();
    await screen.findByTestId("composite-score");
    await user.click(screen.getByRole("button", { name: "Ask Benri" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).not.toHaveProperty("trip");
  });

  it("Show on map previews the area without changing the selection", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByTestId("composite-score");
    await user.click(screen.getByRole("button", { name: "Ask Benri" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "go{Enter}");

    await user.click(await screen.findByRole("button", { name: "Show Darien, CT on map" }));

    expect(map().previewPin).toEqual({ lat: 41.07, lon: -73.47 });
    expect(screen.getByRole("region", { name: "Previewed area" })).toBeInTheDocument();
    expect(window.history.pushState).not.toHaveBeenCalled();
  });

  it("Score this area selects the place and keeps the chat open", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByTestId("composite-score");
    await user.click(screen.getByRole("button", { name: "Ask Benri" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "go{Enter}");

    await user.click(await screen.findByRole("button", { name: "Score Darien, CT" }));

    expect(window.history.pushState).toHaveBeenCalled();
    expect(navigation.search).toContain("lat=41.07");
    expect(screen.getByRole("region", { name: "Ask Benri" })).toBeInTheDocument();
  });

  it("sends the typed, unsubmitted search text as the chat address when nothing is scored", async () => {
    const user = userEvent.setup();
    const { chat } = setup("");
    await user.type(screen.getByRole("combobox", { name: "Address" }), "10 Main St, Stamford");
    await user.click(screen.getByRole("button", { name: "Ask Benri" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).toEqual({
      address: "10 Main St, Stamford",
      factors: [...DEFAULT_FACTOR_KEYS],
    });
  });

  it("sends the street address, not the words Your location, after locating", async () => {
    const user = userEvent.setup();
    const { chat } = setup("address=Your+location&lat=40.7492&lon=-73.985");
    await user.click(screen.getByRole("button", { name: "Ask Benri" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).toMatchObject({
      address: "350 5th Avenue, New York, NY",
      latitude: 40.7492,
      longitude: -73.985,
    });
  });

  it("opens the chat on load for ?chat=1 and pre-fills ?ask= without scoring", async () => {
    const user = userEvent.setup();
    const { chat } = setup("chat=1&ask=12+Elm+St");
    expect(screen.getByRole("region", { name: "Ask Benri" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("12 Elm St");
    expect(window.history.pushState).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).toEqual({
      address: "12 Elm St",
      factors: [...DEFAULT_FACTOR_KEYS],
    });
  });

  it("opens the chat on load for a bare ?chat=1", () => {
    setup("chat=1");
    expect(screen.getByRole("region", { name: "Ask Benri" })).toBeInTheDocument();
  });
});
