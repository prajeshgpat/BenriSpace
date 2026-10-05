import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ComparePlace } from "@/lib/compare";
import { emptySubScores } from "@/test/fixtures";

import { CompareDrawer } from "./CompareDrawer";

const place = (id: string, score: number): ComparePlace => ({
  id,
  label: `Place ${id}`,
  neighborhood: "Park Slope, Brooklyn",
  score,
  subScores: { ...emptySubScores, grocery: score },
  lat: 40,
  lon: -73,
});

describe("CompareDrawer", () => {
  it("renders nothing without pins", () => {
    render(<CompareDrawer places={[]} onRemove={vi.fn()} onClear={vi.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows an accessible table with the best per row marked", async () => {
    const onRemove = vi.fn();
    const onClear = vi.fn();
    render(
      <CompareDrawer places={[place("a", 70), place("b", 82)]} onRemove={onRemove} onClear={onClear} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Compare places \(2\)/ }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
    const overall = within(table).getByRole("row", { name: /Overall score/ });
    expect(within(overall).getByText("(best)").closest("td")).toHaveTextContent("82");
    expect(within(overall).getAllByText(/\(best\)/)).toHaveLength(1);
    // 13 factors + overall
    expect(within(table).getAllByRole("rowheader")).toHaveLength(14);

    await userEvent.click(screen.getByRole("button", { name: "Remove Place a from compare" }));
    expect(onRemove).toHaveBeenCalledWith("a");
    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onClear).toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
