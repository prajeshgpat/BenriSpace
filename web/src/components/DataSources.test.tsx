import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { parseSources } from "@/lib/api/client";

import { DataSources } from "./DataSources";

describe("DataSources", () => {
  it("lists name, feeds, licence link and age", async () => {
    const recent = new Date(Date.now() - 3 * 86_400_000 - 3_600_000).toISOString();
    const getSources = vi.fn(async () =>
      parseSources({
        sources: [
          { id: "osm", name: "OpenStreetMap", feeds: "Places", license: "ODbL", url: "https://osm.org/copyright", lastUpdated: recent },
          { id: "x", name: "Unrun", feeds: "Stuff", license: "PD", url: "javascript:alert(1)", lastUpdated: null },
        ],
      }),
    );
    render(<DataSources client={{ getSources }} />);
    expect(await screen.findByRole("rowheader", { name: "OpenStreetMap" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ODbL" })).toHaveAttribute("href", "https://osm.org/copyright");
    expect(screen.getByText("3 days ago")).toBeInTheDocument();
    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "PD" })).toBeNull();
  });

  it("offers a retry when the list fails", async () => {
    const getSources = vi.fn(async () => {
      throw new ApiError("server", "boom");
    });
    render(<DataSources client={{ getSources }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
