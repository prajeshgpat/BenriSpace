import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { useTripPlanner, type TripPlace } from "@/hooks/useTripPlanner";
import type { Triangulation } from "@/lib/api/types";

import { NO_OVERLAP_MESSAGE, TripPlanner } from "./TripPlanner";

const PLACE: TripPlace = { label: "Home", lat: 40.7, lon: -74, travelMode: "walk" };
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
  const planner = useTripPlanner(props.client, PLACE);
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

const addButton = () => screen.queryByRole("button", { name: /Point of interest/ });

async function fillPoint(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = screen.getByRole("combobox", { name: `${name} address` });
  await user.type(input, "park ave");
  await user.click(await screen.findByRole("option", { name: /Park Ave/ }));
}

describe("TripPlanner", () => {
  it("adds Your place and Point 1, focusing the new address field", async () => {
    const { user, onNeedSpace } = setup();
    await user.click(addButton()!);
    expect(screen.getByRole("group", { name: "Your place" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Point 1" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Your place address" })).toHaveValue("Home");
    expect(screen.getByRole("combobox", { name: "Point 1 address" })).toHaveFocus();
    expect(onNeedSpace).toHaveBeenCalledWith("full");
  });

  it("stops offering the button after Point 2", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    expect(screen.getByRole("group", { name: "Point 2" })).toBeInTheDocument();
    expect(addButton()).toBeNull();
  });

  it("removes a point and returns focus to the add button", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    await user.click(screen.getByRole("button", { name: "Remove Point 1" }));
    expect(screen.queryByRole("group", { name: "Point 2" })).toBeNull();
    expect(screen.getByRole("group", { name: "Point 1" })).toBeInTheDocument();
    expect(addButton()).toHaveFocus();
  });

  it("removes the whole planner with Your place or the last point", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(screen.getByRole("button", { name: "Remove Point 1" }));
    expect(screen.queryByRole("group", { name: "Your place" })).toBeNull();
    expect(addButton()).toHaveFocus();

    await user.click(addButton()!);
    await user.click(screen.getByRole("button", { name: "Remove Your place" }));
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
  });

  it("changes mode and minutes", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    const group = screen.getByRole("group", { name: "Point 1" });
    expect(within(group).getByRole("button", { name: "Train" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByText("20 min")).toBeInTheDocument();
    await user.click(within(group).getByRole("button", { name: "More minutes for Point 1" }));
    expect(within(group).getByText("25 min")).toBeInTheDocument();
    await user.click(within(group).getByRole("button", { name: "Drive" }));
    expect(within(group).getByText("15 min")).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Walk" })).toHaveAttribute("aria-pressed", "false");
  });

  it("lists the best areas, announces them and selects one on click", async () => {
    const { user, onSelectResult, onNeedSpace } = setup();
    await user.click(addButton()!);
    await fillPoint(user, "Point 1");
    const heading = await screen.findByRole("heading", { name: "Best areas in the overlap" });
    expect(heading).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByRole("status").some((s) => s.textContent === "2 areas found in the overlap")).toBe(true),
    );
    expect(onNeedSpace).toHaveBeenCalledWith("half");
    await user.click(screen.getByRole("button", { name: /1 Main St/ }));
    expect(onSelectResult).toHaveBeenCalledWith({ lat: 40.71, lon: -73.99, label: "1 Main St" });
  });

  it("explains an empty overlap", async () => {
    const { user } = setup(vi.fn(async () => response({ combined: iso("network", 0) })));
    await user.click(addButton()!);
    await fillPoint(user, "Point 1");
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
    await fillPoint(user, "Point 1");
    expect(await screen.findByText("Couldn’t work out the overlap.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Best areas in the overlap" })).toBeInTheDocument();
  });

  it("notes straight-line estimates", async () => {
    const { user } = setup(
      vi.fn(async () => response({ isochrones: [iso("estimate"), iso()] })),
    );
    await user.click(addButton()!);
    await fillPoint(user, "Point 1");
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
    await user.type(screen.getByRole("combobox", { name: "Point 1 address" }), "nowhere at all{Enter}");
    expect(await screen.findByText("Couldn't find that address. Pick one from the list.")).toBeInTheDocument();
  });
});
