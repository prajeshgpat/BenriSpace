import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Suggestion } from "@/lib/api/types";

import { AddressSearch } from "./AddressSearch";

const SUGGESTIONS: Suggestion[] = [
  {
    label: "350 5th Avenue, New York, NY",
    latitude: 40.7484,
    longitude: -73.9857,
  },
  { label: "350 5th Street, Brooklyn, NY", latitude: 40.67, longitude: -73.98 },
  { label: "350 5th Road, Queens, NY", latitude: 40.74, longitude: -73.84 },
];

function setup(suggestions: Suggestion[] = SUGGESTIONS) {
  const user = userEvent.setup();
  const suggestAddresses = vi.fn(async () => suggestions);
  const onSearch = vi.fn();
  const onSelectSuggestion = vi.fn();
  render(
    <AddressSearch
      onSearch={onSearch}
      onSelectSuggestion={onSelectSuggestion}
      suggestClient={{ suggestAddresses }}
    />,
  );
  return {
    user,
    suggestAddresses,
    onSearch,
    onSelectSuggestion,
    input: screen.getByRole("combobox", { name: "Address" }),
  };
}

async function open(ctx: ReturnType<typeof setup>) {
  await ctx.user.type(ctx.input, "350 5th");
  await screen.findByRole("listbox");
}

describe("AddressSearch combobox", () => {
  it("exposes the WAI-ARIA combobox attributes", async () => {
    const ctx = setup();
    expect(ctx.input).toHaveAttribute("aria-autocomplete", "list");
    expect(ctx.input).toHaveAttribute("aria-expanded", "false");
    const listboxId = ctx.input.getAttribute("aria-controls")!;
    expect(document.getElementById(listboxId)).toHaveAttribute(
      "role",
      "listbox",
    );

    await open(ctx);

    expect(ctx.input).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(ctx.input).not.toHaveAttribute("aria-activedescendant");
  });

  it("announces the suggestion count politely", async () => {
    const ctx = setup();
    await open(ctx);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("3 suggestions available");
  });

  it("moves the active option with the arrows, wrapping at both ends", async () => {
    const ctx = setup();
    await open(ctx);
    const options = screen.getAllByRole("option");

    await ctx.user.keyboard("{ArrowDown}");
    expect(ctx.input).toHaveAttribute("aria-activedescendant", options[0].id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    await ctx.user.keyboard("{ArrowUp}");
    expect(ctx.input).toHaveAttribute("aria-activedescendant", options[2].id);

    await ctx.user.keyboard("{ArrowDown}");
    expect(ctx.input).toHaveAttribute("aria-activedescendant", options[0].id);

    await ctx.user.keyboard("{End}");
    expect(ctx.input).toHaveAttribute("aria-activedescendant", options[2].id);
    await ctx.user.keyboard("{Home}");
    expect(ctx.input).toHaveAttribute("aria-activedescendant", options[0].id);
  });

  it("selects the active option with Enter instead of submitting", async () => {
    const ctx = setup();
    await open(ctx);

    await ctx.user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(ctx.onSelectSuggestion).toHaveBeenCalledWith(SUGGESTIONS[1]);
    expect(ctx.onSearch).not.toHaveBeenCalled();
    expect(ctx.input).toHaveValue("350 5th Street, Brooklyn, NY");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(ctx.input).toHaveFocus();
  });

  it("submits the typed text with Enter when no option is active", async () => {
    const ctx = setup();
    await open(ctx);

    await ctx.user.keyboard("{Enter}");

    expect(ctx.onSearch).toHaveBeenCalledWith("350 5th");
    expect(ctx.onSelectSuggestion).not.toHaveBeenCalled();
  });

  it("closes on Escape and keeps the typed text", async () => {
    const ctx = setup();
    await open(ctx);

    await ctx.user.keyboard("{ArrowDown}{Escape}");

    expect(ctx.input).toHaveAttribute("aria-expanded", "false");
    expect(ctx.input).toHaveValue("350 5th");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("closes on Tab", async () => {
    const ctx = setup();
    await open(ctx);

    await ctx.user.tab();

    expect(ctx.input).toHaveAttribute("aria-expanded", "false");
  });

  it("selects on click", async () => {
    const ctx = setup();
    await open(ctx);

    await ctx.user.click(screen.getAllByRole("option")[2]);

    expect(ctx.onSelectSuggestion).toHaveBeenCalledWith(SUGGESTIONS[2]);
  });

  it("reopens with ArrowDown after Escape", async () => {
    const ctx = setup();
    await open(ctx);
    await ctx.user.keyboard("{Escape}{ArrowDown}");

    expect(ctx.input).toHaveAttribute("aria-expanded", "true");
    expect(ctx.input).toHaveAttribute("aria-activedescendant");
  });

  it("does not request suggestions for fewer than 3 characters", async () => {
    const ctx = setup();
    await ctx.user.type(ctx.input, "35");
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(ctx.suggestAddresses).not.toHaveBeenCalled();
  });

  it("stays a plain search box when no suggestion handler is given", async () => {
    render(<AddressSearch onSearch={() => {}} />);
    const input = screen.getByRole("textbox", { name: "Address" });
    expect(input).not.toHaveAttribute("aria-expanded");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("stays quiet when the lookup throws", async () => {
    const user = userEvent.setup();
    const suggestAddresses = vi.fn(async () => {
      throw new Error("503");
    });
    render(
      <AddressSearch
        onSearch={() => {}}
        onSelectSuggestion={() => {}}
        suggestClient={{ suggestAddresses }}
      />,
    );
    const input = screen.getByRole("combobox", { name: "Address" });

    await user.type(input, "350 5th");
    await waitFor(() => expect(suggestAddresses).toHaveBeenCalled());

    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
