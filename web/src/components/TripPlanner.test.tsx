import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { useTripPlanner, type TripPlace } from "@/hooks/useTripPlanner";
import type { Triangulation } from "@/lib/api/types";

import { NO_OVERLAP_MESSAGE, TripPlanner } from "./TripPlanner";

const PLACE: TripPlace = { label: "Home", lat: 40.7, lon: -74 };
const PARK = { label: "Park Ave, NY", latitude: 40.75, longitude: -73.97 };

const iso = (method: "network" | "estimate" = "network", cellCount = 3) => ({
  label: null,
  mode: "drive" as const,
  minutes: 15,
  method,
  areaSqMi: 1,
  cellCount,
  geometry: null,
});

function response(overrides: Partial<Triangulation> = {}): Triangulation {
  return {
    results: [
      { lat: 40.71, lon: -73.99, score: 81.4, address: "1 Main St" },
      { lat: 40.8, lon: -73.9, score: 70, address: "2 Side St" },
    ],
    isochrones: [iso(), iso()],
    combined: iso(),
    ...overrides,
  };
}

function Harness(props: {
  client: never;
  onSelectResult: (r: { lat: number; lon: number; label: string }) => void;
  onNeedSpace?: (k: "full" | "half") => void;
}) {
  const planner = useTripPlanner(props.client, PLACE, { mode: "transit", minutes: 20 });
  return (
    <TripPlanner
      planner={planner}
      client={props.client}
      onSelectResult={props.onSelectResult}
      onNeedSpace={props.onNeedSpace}
    />
  );
}

function setup(triangulate = vi.fn(async () => response())) {
  const client = {
    triangulate,
    reverseGeocode: vi.fn(async () => ({ label: null, latitude: 0, longitude: 0 })),
    suggestAddresses: vi.fn(async () => [PARK]),
  } as never;
  const onSelectResult = vi.fn();
  const onNeedSpace = vi.fn();
  const user = userEvent.setup();
  render(<Harness client={client} onSelectResult={onSelectResult} onNeedSpace={onNeedSpace} />);
  return { user, triangulate, onSelectResult, onNeedSpace };
}

const addButton = () => screen.queryByRole("button", { name: "Point of interest" });

async function fillPoint(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = screen.getByRole("combobox", { name: `${name} address` });
  await user.type(input, "park ave");
  await user.click(await screen.findByRole("option", { name: /Park Ave/ }));
}

describe("TripPlanner", () => {
  it("starts with just the pill and no cards", () => {
    setup();
    expect(addButton()).toBeInTheDocument();
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(screen.queryByText("Your place")).toBeNull();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("opens a small box to the left of the pill and focuses it", async () => {
    const { user, onNeedSpace } = setup();
    await user.click(addButton()!);
    const box = screen.getByRole("combobox", { name: "Point of interest 1 address" });
    expect(box).toHaveFocus();
    expect(box).toHaveAttribute("placeholder", "Point of interest 1");
    expect(box.compareDocumentPosition(addButton()!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove point of interest 1" })).toBeInTheDocument();
    expect(onNeedSpace).toHaveBeenCalledWith("full");
  });

  it("opens the second box on the next click and the pill disappears", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    const boxes = screen.getAllByRole("combobox");
    expect(boxes.map((b) => b.getAttribute("placeholder"))).toEqual([
      "Point of interest 1",
      "Point of interest 2",
    ]);
    expect(boxes[1]).toHaveFocus();
    expect(addButton()).toBeNull();
  });

  it("removes a point with its x, renumbers the other, brings the pill back and focuses it", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    await user.type(screen.getByRole("combobox", { name: "Point of interest 2 address" }), "abc");
    await user.click(screen.getByRole("button", { name: "Remove point of interest 1" }));
    const boxes = screen.getAllByRole("combobox");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toHaveAccessibleName("Point of interest 1 address");
    expect(boxes[0]).toHaveValue("abc");
    expect(addButton()).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Remove point of interest 1" }));
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(addButton()).toHaveFocus();
  });

  it("lists the best areas, announces them and selects one on click", async () => {
    const { user, onSelectResult, onNeedSpace } = setup();
    await user.click(addButton()!);
    await fillPoint(user, "Point of interest 1");
    const heading = await screen.findByRole("heading", { name: "Best areas in the overlap" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Best areas in the overlap" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByRole("status").some((s) => s.textContent === "2 areas found in the overlap")).toBe(true),
    );
    expect(onNeedSpace).toHaveBeenCalledWith("half");
    await user.click(screen.getByRole("button", { name: /1 Main St/ }));
    expect(onSelectResult).toHaveBeenCalledWith({ lat: 40.71, lon: -73.99, label: "1 Main St" });
  });

  it("shows a legend with only the places in use", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    const legend = screen.getByRole("list", { name: "Map legend" });
    expect(legend.textContent).toBe("Searched placePoint of interest 1Overlap");
    expect(legend.textContent).not.toContain("Point of interest 2");
    await user.click(addButton()!);
    expect(screen.getByRole("list", { name: "Map legend" }).textContent).toBe(
      "Searched placePoint of interest 1Point of interest 2Overlap",
    );
  });

  it("explains an empty overlap", async () => {
    const { user } = setup(vi.fn(async () => response({ combined: iso("network", 0) })));
    await user.click(addButton()!);
    await fillPoint(user, "Point of interest 1");
    expect((await screen.findAllByText(NO_OVERLAP_MESSAGE)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: "Best areas in the overlap" })).toBeNull();
  });

  it("shows an error with a working retry", async () => {
    const triangulate = vi
      .fn<() => Promise<Triangulation>>()
      .mockRejectedValueOnce(new Error("x"))
      .mockResolvedValue(response());
    const { user } = setup(triangulate);
    await user.click(addButton()!);
    await fillPoint(user, "Point of interest 1");
    expect(await screen.findByText("Couldn’t work out the overlap.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Best areas in the overlap" })).toBeInTheDocument();
  });

  it("notes straight-line estimates", async () => {
    const { user } = setup(
      vi.fn(async () => response({ isochrones: [iso("estimate"), iso()] })),
    );
    await user.click(addButton()!);
    await fillPoint(user, "Point of interest 1");
    expect(await screen.findByText(/straight-line estimate/)).toBeInTheDocument();
  });

  it("resolves typed text on Enter and reports a miss", async () => {
    const user = userEvent.setup();
    const client = {
      triangulate: vi.fn(async () => response()),
      reverseGeocode: vi.fn(async () => ({ label: null, latitude: 0, longitude: 0 })),
      suggestAddresses: vi.fn(async (_q: string, o?: { limit?: number }) => (o?.limit === 1 ? [] : [PARK])),
    } as never;
    render(<Harness client={client} onSelectResult={() => {}} />);
    await user.click(addButton()!);
    await user.type(screen.getByRole("combobox", { name: "Point of interest 1 address" }), "nowhere at all{Enter}");
    expect(await screen.findByText("Couldn't find that address. Pick one from the list.")).toBeInTheDocument();
  });
});
