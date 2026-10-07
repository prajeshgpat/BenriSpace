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
  onSelectResult: (r: { lat: number; lon: number; label: string; score: number }) => void;
  selectedKey?: string | null;
  onNeedSpace?: (k: "full" | "half") => void;
}) {
  const planner = useTripPlanner(props.client, PLACE, { mode: "transit", minutes: 20 });
  return (
    <TripPlanner
      planner={planner}
      client={props.client}
      onSelectResult={props.onSelectResult}
      selectedKey={props.selectedKey}
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

  it("opens a pill to the left of the add pill, armed to drop a pin and without focusing it", async () => {
    const { user, onNeedSpace } = setup();
    await user.click(addButton()!);
    const box = screen.getByRole("combobox", { name: "Point of interest 1 address" });
    // No focus: that would open the phone's keyboard before the map has been tried.
    expect(box).not.toHaveFocus();
    expect(box).toHaveAttribute("placeholder", "Drop a pin");
    expect(box.closest("[data-poi-box]")).toHaveAttribute("data-armed");
    expect(box.compareDocumentPosition(addButton()!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove point of interest 1" })).toBeInTheDocument();
    expect(onNeedSpace).toHaveBeenCalledWith("half");
  });

  it("the first tap on an idle box arms it and the second focuses the input", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    const [first, second] = screen.getAllByRole("combobox");
    // The newest box is armed; the other still shows its name.
    expect(first).toHaveAttribute("placeholder", "Point of interest 1");
    expect(second).toHaveAttribute("placeholder", "Drop a pin");

    await user.click(screen.getByTestId("poi-tap-1"));
    expect(first).toHaveAttribute("placeholder", "Drop a pin");
    expect(second).toHaveAttribute("placeholder", "Point of interest 2");
    expect(first).not.toHaveFocus();

    await user.click(screen.getByTestId("poi-tap-1"));
    expect(first).toHaveFocus();
  });

  it("focusing the input by keyboard arms the box", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    const [first] = screen.getAllByRole("combobox");
    await user.click(first);
    expect(first.closest("[data-poi-box]")).toHaveAttribute("data-armed");
  });

  it("opens the second box on the next click and the pill disappears", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    await user.click(addButton()!);
    const boxes = screen.getAllByRole("combobox");
    expect(boxes.map((b) => b.getAttribute("aria-label") ?? b.id)).toHaveLength(2);
    expect(addButton()).toBeNull();
  });

  it("opens a dropdown from the mode segment: other modes, minutes, and applies a choice", async () => {
    const { user, triangulate } = setup();
    await user.click(addButton()!);
    await fillPoint(user, "Point of interest 1");
    const toggle = screen.getByRole("button", { name: /^Travel for Point of interest 1/ });
    // Follows the main Travel time (a 20 minute train) until set apart.
    expect(toggle).toHaveAccessibleName("Travel for Point of interest 1: Train, 20 minutes");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("group", { name: "Minutes for Point of interest 1" })).toBeNull();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const modes = screen.getByRole("group", { name: "Travel mode for Point of interest 1" });
    expect(Array.from(modes.querySelectorAll("button")).map((b) => b.getAttribute("aria-label"))).toEqual([
      "Walk",
      "Drive",
    ]);
    expect(screen.getByRole("group", { name: "Minutes for Point of interest 1" })).toHaveTextContent("20 min");

    await user.click(screen.getByRole("button", { name: "More minutes for Point of interest 1" }));
    expect(screen.getByRole("group", { name: "Minutes for Point of interest 1" })).toHaveTextContent("25 min");

    // A new mode takes its own starting minutes, and the dropdown stays open.
    await user.click(screen.getByRole("button", { name: "Walk" }));
    expect(toggle).toHaveAccessibleName("Travel for Point of interest 1: Walk, 10 minutes");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      Array.from(
        screen
          .getByRole("group", { name: "Travel mode for Point of interest 1" })
          .querySelectorAll("button"),
      ).map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Train", "Drive"]);

    // The overlap is asked again with this point's own travel.
    await waitFor(() => {
      const last = triangulate.mock.calls.at(-1) as unknown as [{ mode: string; minutes: number }[]];
      expect(last[0].map((a) => [a.mode, a.minutes])).toEqual([
        ["transit", 20],
        ["walk", 10],
      ]);
    });

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the dropdown on a press outside it", async () => {
    const { user } = setup();
    await user.click(addButton()!);
    const toggle = screen.getByRole("button", { name: /^Travel for Point of interest 1/ });
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(document.body);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
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
    expect(onSelectResult).toHaveBeenCalledWith({
      lat: 40.71,
      lon: -73.99,
      label: "1 Main St",
      score: 81.4,
    });
  });

  it("marks the result on show as pressed", async () => {
    const user = userEvent.setup();
    const client = {
      triangulate: vi.fn(async () => response()),
      reverseGeocode: vi.fn(async () => ({ label: null, latitude: 0, longitude: 0 })),
      suggestAddresses: vi.fn(async () => [PARK]),
    } as never;
    render(<Harness client={client} onSelectResult={() => {}} selectedKey="40.71,-73.99" />);
    await user.click(addButton()!);
    await fillPoint(user, "Point of interest 1");
    expect(await screen.findByRole("button", { name: /1 Main St/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /2 Side St/ })).toHaveAttribute("aria-pressed", "false");
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
