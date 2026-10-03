import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Suggestion } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

import { SUGGEST_DEBOUNCE_MS } from "@/hooks/useAddressSuggestions";

import { HomeSearch } from "./HomeSearch";

const suggestion: Suggestion = {
  label: "350 5th Ave, New York, NY",
  latitude: 40.7484,
  longitude: -73.9857,
} as Suggestion;

function setup() {
  const suggestAddresses = vi.fn().mockResolvedValue([suggestion]);
  render(<HomeSearch suggestClient={{ suggestAddresses }} />);
  return { suggestAddresses, input: screen.getByRole("combobox", { name: "Address" }) };
}

describe("HomeSearch", () => {
  beforeEach(() => {
    push.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  async function type(input: HTMLElement, text: string) {
    fireEvent.change(input, { target: { value: text } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SUGGEST_DEBOUNCE_MS + 10);
    });
  }

  it("keeps the native GET form fallback", () => {
    const { input } = setup();
    const form = input.closest("form")!;
    expect(form).toHaveAttribute("action", "/app");
    expect(form).toHaveAttribute("method", "get");
    expect(input).toHaveAttribute("name", "address");
  });

  it("shows suggestions while typing", async () => {
    const { input, suggestAddresses } = setup();
    await type(input, "350 5th");
    expect(suggestAddresses).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("option", { name: /350 5th Ave/ })).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-expanded", "true");
  });

  it("navigates with coordinates when a suggestion is clicked", async () => {
    const { input } = setup();
    await type(input, "350 5th");
    fireEvent.click(screen.getByRole("option", { name: /350 5th Ave/ }));
    expect(push).toHaveBeenCalledTimes(1);
    const url = new URL(push.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/app");
    expect(url.searchParams.get("address")).toBe(suggestion.label);
    expect(url.searchParams.get("lat")).toBe("40.7484");
    expect(url.searchParams.get("lon")).toBe("-73.9857");
  });

  it("selects the active suggestion with the keyboard", async () => {
    const { input } = setup();
    await type(input, "350 5th");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0][0]).toContain("lat=40.7484");
  });

  it("searches the typed address on Enter when nothing is active", async () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "  1 Main   St " } });
    fireEvent.submit(input.closest("form")!);
    expect(push).toHaveBeenCalledWith("/app?address=1+Main+St");
  });

  it("shows an error and does not navigate for too-short input", () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "ab" } });
    fireEvent.submit(input.closest("form")!);
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
