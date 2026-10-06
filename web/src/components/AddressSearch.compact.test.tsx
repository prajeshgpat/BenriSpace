import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Suggestion } from "@/lib/api/types";

import { AddressSearch } from "./AddressSearch";

const SUGGESTIONS: Suggestion[] = [
  { label: "350 5th Avenue, New York, NY", latitude: 40.7484, longitude: -73.9857 },
  { label: "350 5th Street, Brooklyn, NY", latitude: 40.67, longitude: -73.98 },
];

describe("AddressSearch compact", () => {
  function setup() {
    const user = userEvent.setup();
    const suggestAddresses = vi.fn(async () => SUGGESTIONS);
    const onSelectSuggestion = vi.fn();
    const onClear = vi.fn();
    const onSearch = vi.fn();
    render(
      <AddressSearch
        compact
        label="Point 1 address"
        placeholder="Add an address"
        onSearch={onSearch}
        onClear={onClear}
        onSelectSuggestion={onSelectSuggestion}
        suggestClient={{ suggestAddresses }}
      />,
    );
    return {
      user,
      onSelectSuggestion,
      onClear,
      onSearch,
      input: screen.getByRole("combobox", { name: "Point 1 address" }),
    };
  }

  it("has no submit button, keeps autocomplete and submits on Enter", async () => {
    const ctx = setup();
    expect(screen.queryByRole("button", { name: "Get score" })).toBeNull();
    expect(ctx.input).toHaveAttribute("placeholder", "Add an address");
    await ctx.user.type(ctx.input, "350 5th");
    await screen.findByRole("listbox");
    await ctx.user.click(screen.getAllByRole("option")[0]);
    expect(ctx.onSelectSuggestion).toHaveBeenCalledWith(SUGGESTIONS[0]);
    await ctx.user.type(ctx.input, "{Enter}");
    expect(ctx.onSearch).toHaveBeenCalled();
  });

  it("clears the field with the x button and refocuses it", async () => {
    const ctx = setup();
    await ctx.user.type(ctx.input, "abc");
    await ctx.user.click(screen.getByRole("button", { name: "Clear point 1 address" }));
    expect(ctx.input).toHaveValue("");
    expect(ctx.input).toHaveFocus();
    expect(ctx.onClear).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Clear/ })).toBeNull();
  });

  it("uses a custom submit label when not compact", () => {
    render(<AddressSearch submitLabel="Go" />);
    expect(screen.getByRole("button", { name: "Go" })).toBeInTheDocument();
  });
});
