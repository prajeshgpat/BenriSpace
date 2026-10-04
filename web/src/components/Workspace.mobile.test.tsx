import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createApiClient, type ApiClient } from "@/lib/api/client";
import { jsonResponse, liveExplanationBody, liveScoreBody } from "@/test/fixtures";

import { Workspace } from "./Workspace";

const navigation = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => {
    const search = navigation.search;
    return useMemo(() => new URLSearchParams(search), [search]);
  },
}));

vi.mock("./map/MapCanvas", () => ({
  MapCanvas: () => <div data-testid="map" />,
}));

function setup(search: string) {
  navigation.search = search;
  const fetchMock = vi.fn<typeof fetch>(async (input) =>
    String(input).includes("/explanation")
      ? jsonResponse(liveExplanationBody)
      : jsonResponse(liveScoreBody),
  );
  const client: ApiClient = {
    ...createApiClient({ baseUrl: "http://api.test/v1", fetch: fetchMock }),
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
  };
  return render(<Workspace client={client} />);
}

beforeEach(() => {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        matches: true,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
  window.history.replaceState(null, "", "/app");
  vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
});

const sheet = () => screen.getByRole("complementary");

describe("Workspace on a phone", () => {
  it("starts collapsed, with the search first and no welcome text", () => {
    setup("");
    expect(sheet()).toHaveAttribute("data-snap", "peek");
    expect(screen.getByRole("combobox", { name: "Address" })).toBeInTheDocument();
    expect(screen.queryByText(/click the map to see its score/)).not.toBeInTheDocument();
  });

  it("opens to half without any welcome text", async () => {
    setup("");
    await userEvent.click(screen.getByRole("button", { name: "Resize results panel" }));
    expect(sheet()).toHaveAttribute("data-snap", "half");
    expect(screen.queryByText(/click the map to see its score/)).not.toBeInTheDocument();
  });

  it("opens at half when the URL already holds a result", async () => {
    setup("address=350+5th+Ave%2C+New+York%2C+NY");
    expect(sheet()).toHaveAttribute("data-snap", "half");
    expect(await screen.findByRole("button", { name: /close result/i })).toBeInTheDocument();
  });
});
