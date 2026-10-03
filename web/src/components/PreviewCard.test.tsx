import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Preview } from "@/lib/map/preview";

import { PreviewCard } from "./PreviewCard";

const PREVIEW: Preview = {
  lat: 40.2,
  lon: -74,
  label: "Area bounded by Road 2",
  kind: "similar",
  summary: {
    compositeScore: 71.4,
    distanceLabel: "2 mi",
    direction: "SE",
    differences: [
      { label: "transit", delta: 7 },
      { label: "grocery", delta: -6 },
      { label: "cafe", delta: 9 },
      { label: "bar", delta: 8 },
    ],
  },
};

function setup() {
  const handlers = { onBack: vi.fn(), onPromote: vi.fn(), onClose: vi.fn() };
  render(
    <PreviewCard preview={PREVIEW} originLabel="350 5th Ave, New York, NY" {...handlers} />,
  );
  return handlers;
}

describe("PreviewCard", () => {
  it("is a labelled region with a score, three chips and the distance", () => {
    setup();
    const region = screen.getByRole("region", { name: "Previewed area" });
    expect(region).toHaveTextContent("Area bounded by Road 2");
    expect(screen.getByLabelText("Score 71")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(region).toHaveTextContent("2 mi SE");
    expect(screen.getByRole("status")).toHaveTextContent(/Previewing Area bounded by Road 2/);
  });

  it("names the place it returns to and wires every button", async () => {
    const h = setup();
    await userEvent.click(screen.getByRole("button", { name: "Back to 350 5th Ave" }));
    await userEvent.click(screen.getByRole("button", { name: "Score this area" }));
    await userEvent.click(screen.getByRole("button", { name: "Close preview" }));
    expect(h.onBack).toHaveBeenCalledOnce();
    expect(h.onPromote).toHaveBeenCalledOnce();
    expect(h.onClose).toHaveBeenCalledOnce();
  });

  it("closes on Escape from within the card, not from elsewhere", () => {
    const h = setup();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(h.onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("button", { name: "Score this area" }), { key: "Escape" });
    expect(h.onClose).toHaveBeenCalledOnce();
  });
});
