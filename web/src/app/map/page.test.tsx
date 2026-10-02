import { describe, expect, it, vi } from "vitest";

import LegacyMapPage from "./page";

const redirect = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ redirect }));

describe("/map", () => {
  it("sends old map links to the app with the view as a centre", async () => {
    await LegacyMapPage({
      searchParams: Promise.resolve({
        lat: "40.75",
        lon: "-73.99",
        z: "13",
        factors: "transit",
      }),
    });

    expect(redirect).toHaveBeenCalledWith(
      "/app?z=13&factors=transit&center=40.7500%2C-73.9900",
    );
  });

  it("goes to the plain app when there is nothing to carry over", async () => {
    await LegacyMapPage({ searchParams: Promise.resolve({}) });
    expect(redirect).toHaveBeenCalledWith("/app");
  });
});
