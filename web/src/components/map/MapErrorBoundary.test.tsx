import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MapErrorBoundary } from "./MapErrorBoundary";

let shouldThrow = true;
function Bomb() {
  if (shouldThrow) throw new TypeError("null is not an object");
  return <p>map ok</p>;
}

describe("MapErrorBoundary", () => {
  it("shows a reload prompt instead of crashing, and remounts on reload", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    shouldThrow = true;
    render(
      <MapErrorBoundary>
        <Bomb />
      </MapErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("The map hit a problem");
    shouldThrow = false;
    await userEvent.click(screen.getByRole("button", { name: "Reload map" }));
    expect(screen.getByText("map ok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
