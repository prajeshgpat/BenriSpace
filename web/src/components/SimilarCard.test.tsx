import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";

import { SimilarCard } from "./SimilarCard";

function result(i: number, overrides: Record<string, unknown> = {}) {
  return {
    latitude: 40 + i / 10,
    longitude: -74,
    direction: "SE",
    distanceLabel: `${i} mi`,
    similarity: 88,
    compositeScore: 71.4,
    areaLabel: `Area bounded by Road ${i}`,
    differences: [
      { factor: "transit", label: "transit", delta: 7 },
      { factor: "grocery", label: "grocery", delta: -6 },
      { factor: "cafe", label: "cafe", delta: 9 },
      { factor: "bar", label: "bar", delta: 8 },
    ],
    summary: "",
    ...overrides,
  };
}

const BODY = {
  minSeparationMi: 1,
  priorities: [],
  results: [1, 2, 3, 4, 5, 6].map((i) => result(i)),
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const clientWith = (fetchImpl: typeof fetch) =>
  createApiClient({ baseUrl: "http://api.test", fetch: fetchImpl });

const POINT = { lat: 40, lon: -74 };

describe("SimilarCard", () => {
  it("renders up to five rows with name, distance, similarity, score and chips", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json(BODY));
    render(
      <SimilarCard coordinates={POINT} client={clientWith(fetchMock)} onFocusPoint={vi.fn()} />,
    );

    expect(await screen.findByText("Similar areas")).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/similar?");
    expect(screen.getAllByRole("button", { name: /Show similar area/ })).toHaveLength(5);
    expect(screen.getByText("Area bounded by Road 1")).toBeInTheDocument();
    expect(screen.queryByText("Area bounded by Road 6")).not.toBeInTheDocument();
    expect(screen.getAllByText(/1 mi SE · 88% similar/)).toHaveLength(1);
    expect(screen.getAllByLabelText("Score 71")).toHaveLength(5);

    const first = screen.getAllByRole("list", { name: "Differences from here" })[0];
    const chips = Array.from(first.querySelectorAll("li")).map((li) => li.textContent);
    expect(chips).toEqual(["+7 transit", "−6 grocery", "+9 cafe"]);
  });

  it("falls back to the direction when the area has no name", async () => {
    render(
      <SimilarCard
        coordinates={POINT}
        client={clientWith(async () => json({ ...BODY, results: [result(1, { areaLabel: null })] }))}
        onFocusPoint={vi.fn()}
      />,
    );
    expect(await screen.findByText("Area to the SE")).toBeInTheDocument();
  });

  it("shows a skeleton while loading", () => {
    render(
      <SimilarCard
        coordinates={POINT}
        client={clientWith(() => new Promise<Response>(() => {}))}
        onFocusPoint={vi.fn()}
      />,
    );
    expect(screen.getByTestId("similar-skeleton")).toHaveAttribute("aria-busy", "true");
  });

  it("focuses the map on the chosen row", async () => {
    const onFocusPoint = vi.fn();
    render(
      <SimilarCard
        coordinates={POINT}
        client={clientWith(async () => json(BODY))}
        onFocusPoint={onFocusPoint}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Show similar area 2 on map" }));
    expect(onFocusPoint).toHaveBeenCalledWith(40.2, -74);
  });

  it("hides itself on error and when there are no results", async () => {
    const failing = vi.fn<typeof fetch>(async () => json({}, 404));
    const a = render(
      <SimilarCard coordinates={POINT} client={clientWith(failing)} onFocusPoint={vi.fn()} />,
    );
    await waitFor(() => expect(failing).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("similar-skeleton")).not.toBeInTheDocument());
    expect(a.container).toBeEmptyDOMElement();
    a.unmount();

    const empty = render(
      <SimilarCard
        coordinates={POINT}
        client={clientWith(async () => json({ ...BODY, results: [] }))}
        onFocusPoint={vi.fn()}
      />,
    );
    await waitFor(() => expect(screen.queryByTestId("similar-skeleton")).not.toBeInTheDocument());
    expect(empty.container).toBeEmptyDOMElement();
  });

  it("ignores a stale response for a previous point", async () => {
    let resolveFirst: (r: Response) => void = () => {};
    const fetchMock = vi.fn<typeof fetch>((input) =>
      String(input).includes("lat=40&")
        ? new Promise<Response>((resolve) => {
            resolveFirst = resolve;
          })
        : Promise.resolve(json({ ...BODY, results: [result(1, { areaLabel: "Second point" })] })),
    );
    const client = clientWith(fetchMock);
    const { rerender } = render(
      <SimilarCard coordinates={POINT} client={client} onFocusPoint={vi.fn()} />,
    );
    rerender(
      <SimilarCard coordinates={{ lat: 41, lon: -74 }} client={client} onFocusPoint={vi.fn()} />,
    );
    expect(await screen.findByText("Second point")).toBeInTheDocument();
    resolveFirst(json({ ...BODY, results: [result(1, { areaLabel: "Stale point" })] }));
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.queryByText("Stale point")).not.toBeInTheDocument();
  });

  it("sends the selected factors", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json(BODY));
    render(
      <SimilarCard
        coordinates={POINT}
        client={clientWith(fetchMock)}
        priorities={{ factors: ["transit", "cafe"] }}
        onFocusPoint={vi.fn()}
      />,
    );
    await screen.findByText("Similar areas");
    expect(new URL(String(fetchMock.mock.calls[0][0])).searchParams.get("factors")).toBe(
      "transit,cafe",
    );
  });
});
