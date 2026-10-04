import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";

import { ImproveCard } from "./ImproveCard";

const BODY = {
  composite: 60,
  radiusMi: 1,
  suggestions: [
    {
      factor: "grocery",
      label: "Grocery stores",
      score: 32.4,
      places: [
        {
          name: "Fresh Mart",
          brand: null,
          distanceMi: 0.3,
          distanceLabel: "0.3 mi",
          direction: "NE",
          latitude: 40.1,
          longitude: -74.1,
        },
      ],
      betterArea: {
        latitude: 40.2,
        longitude: -74.2,
        direction: "N",
        distanceMi: 0.5,
        distanceLabel: "0.5 mi",
        factorScore: 70,
        factorGain: 38,
        compositeScore: 66,
        compositeGain: 6,
      },
      tip: "Groceries are a bit far.",
    },
  ],
  bestNearby: {
    latitude: 40.3,
    longitude: -74.3,
    direction: "NE",
    distanceLabel: "0.4 mi",
    compositeScore: 69,
    compositeGain: 9,
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientWith(fetchImpl: typeof fetch) {
  return createApiClient({ baseUrl: "http://api.test", fetch: fetchImpl });
}

const POINT = { lat: 40, lon: -74 };

describe("ImproveCard", () => {
  it("renders suggestions, places and the best move", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json(BODY));
    render(
      <ImproveCard coordinates={POINT} client={clientWith(fetchMock)} onPreview={vi.fn()} />,
    );

    expect(await screen.findByText("Improve this area")).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/improve?");
    expect(screen.getByText("Grocery stores")).toBeInTheDocument();
    expect(screen.getByText("Groceries are a bit far.")).toBeInTheDocument();
    expect(screen.getByText(/Fresh Mart · 0\.3 mi · NE/)).toBeInTheDocument();
    expect(screen.getByText(/\+9 overall, 0\.4 mi NE/)).toBeInTheDocument();
  });

  it("hides itself when the request fails", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json({}, 500));
    const { container } = render(
      <ImproveCard coordinates={POINT} client={clientWith(fetchMock)} onPreview={vi.fn()} />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId("improve-skeleton")).not.toBeInTheDocument(),
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("previews the better area and the best move", async () => {
    const onPreview = vi.fn();
    render(
      <ImproveCard
        coordinates={POINT}
        client={clientWith(async () => json(BODY))}
        onPreview={onPreview}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /better area for Grocery/ }));
    expect(onPreview).toHaveBeenLastCalledWith(
      expect.objectContaining({ lat: 40.2, lon: -74.2, kind: "improve" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /best move nearby/i }));
    expect(onPreview).toHaveBeenLastCalledWith(
      expect.objectContaining({ lat: 40.3, lon: -74.3, kind: "best-move" }),
    );
  });

  it("ignores a stale response for a previous point", async () => {
    let resolveFirst: (r: Response) => void = () => {};
    const fetchMock = vi.fn<typeof fetch>((input) =>
      String(input).includes("lat=40&")
        ? new Promise<Response>((resolve) => {
            resolveFirst = resolve;
          })
        : Promise.resolve(
            json({
              ...BODY,
              suggestions: [{ ...BODY.suggestions[0], tip: "Second point tip." }],
            }),
          ),
    );
    const client = clientWith(fetchMock);
    const { rerender } = render(
      <ImproveCard coordinates={POINT} client={client} onPreview={vi.fn()} />,
    );
    rerender(
      <ImproveCard coordinates={{ lat: 41, lon: -74 }} client={client} onPreview={vi.fn()} />,
    );
    expect(await screen.findByText("Second point tip.")).toBeInTheDocument();
    resolveFirst(json({ ...BODY, suggestions: [{ ...BODY.suggestions[0], tip: "Stale tip." }] }));
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.queryByText("Stale tip.")).not.toBeInTheDocument();
    expect(screen.getByText("Second point tip.")).toBeInTheDocument();
  });

  it("is always expanded and shows only the top three suggestions until Show more", async () => {
    const suggestion = (factor: string, label: string) => ({
      ...BODY.suggestions[0],
      factor,
      label,
      betterArea: { ...BODY.suggestions[0].betterArea, neighborhood: "Park Slope, Brooklyn" },
    });
    const body = {
      ...BODY,
      bestNearby: { ...BODY.bestNearby, neighborhood: "Fort Greene, Brooklyn" },
      suggestions: [
        suggestion("grocery", "Groceries"),
        suggestion("cafe", "Cafes"),
        suggestion("bar", "Bars"),
        suggestion("gym", "Gym"),
        suggestion("transit", "Public transit"),
      ],
    };
    const onPreview = vi.fn();
    render(
      <ImproveCard
        coordinates={POINT}
        client={clientWith(async () => json(body))}
        onPreview={onPreview}
      />,
    );
    expect(await screen.findByText("Improve this area")).toBeInTheDocument();
    expect(document.querySelector("details")).toBeNull();
    expect(screen.queryByText("Gym")).not.toBeInTheDocument();
    const more = screen.getByRole("button", { name: "Show 2 more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    expect(screen.getByText("Gym")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("button", { name: "Show better area for Groceries on map" }));
    expect(onPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        label: "Park Slope, Brooklyn",
        subtitle: "Better area for Groceries",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Show best move nearby on map" }));
    expect(onPreview).toHaveBeenLastCalledWith(
      expect.objectContaining({ label: "Fort Greene, Brooklyn", subtitle: "Best move nearby" }),
    );
  });
});
