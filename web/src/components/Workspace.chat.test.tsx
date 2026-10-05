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

function setup(search = "address=350+5th+Ave&lat=40.7484&lon=-73.9857") {
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
    reverseGeocode: vi.fn(async ({ lat, lon }) => ({ label: null, latitude: lat, longitude: lon })),
    getImprove: vi.fn(async () => { throw new Error("improve unavailable"); }),
    getSimilar: vi.fn(async () => { throw new Error("similar unavailable"); }),
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

describe("Workspace: Ask BenriSpace", () => {
  it("opens the chat in a dock beside the results, with live place and filter context", async () => {
    const user = userEvent.setup();
    const { chat } = setup();
    await screen.findByTestId("composite-score");

    await user.click(screen.getByRole("button", { name: "Ask BenriSpace" }));

    expect(screen.getByRole("region", { name: "Ask BenriSpace" })).toBeInTheDocument();
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

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("region", { name: "Ask BenriSpace" })).not.toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toBeInTheDocument();
  });

  it("Show on map previews the area without changing the selection", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByTestId("composite-score");
    await user.click(screen.getByRole("button", { name: "Ask BenriSpace" }));
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
    await user.click(screen.getByRole("button", { name: "Ask BenriSpace" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "go{Enter}");

    await user.click(await screen.findByRole("button", { name: "Score Darien, CT" }));

    expect(window.history.pushState).toHaveBeenCalled();
    expect(navigation.search).toContain("lat=41.07");
    expect(screen.getByRole("region", { name: "Ask BenriSpace" })).toBeInTheDocument();
  });

  it("sends the typed, unsubmitted search text as the chat address when nothing is scored", async () => {
    const user = userEvent.setup();
    const { chat } = setup("");
    await user.type(screen.getByRole("combobox", { name: "Address" }), "10 Main St, Stamford");
    await user.click(screen.getByRole("button", { name: "Ask BenriSpace" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).toEqual({ address: "10 Main St, Stamford" });
  });

  it("opens the chat on load for ?chat=1 and pre-fills ?ask= without scoring", async () => {
    const user = userEvent.setup();
    const { chat } = setup("chat=1&ask=12+Elm+St");
    expect(screen.getByRole("region", { name: "Ask BenriSpace" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("12 Elm St");
    expect(window.history.pushState).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "hi{Enter}");
    await screen.findByText("Darien looks best.");
    expect(chat.mock.calls[0][1]).toEqual({ address: "12 Elm St" });
  });

  it("opens the chat on load for a bare ?chat=1", () => {
    setup("chat=1");
    expect(screen.getByRole("region", { name: "Ask BenriSpace" })).toBeInTheDocument();
  });
});
