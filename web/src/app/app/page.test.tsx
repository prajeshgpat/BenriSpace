import { describe, expect, it, vi } from "vitest";

const preconnect = vi.fn();
vi.mock("react-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-dom")>()),
  preconnect: (...args: unknown[]) => preconnect(...args),
}));
vi.mock("@/components/Workspace", () => ({
  Workspace: () => null,
  WorkspaceFallback: () => null,
}));

import AppPage from "./page";

describe("/app page", () => {
  it("preconnects to the API and basemap origins once each, in CORS mode", () => {
    AppPage();
    const origins = preconnect.mock.calls.map(([origin]) => origin);
    expect(origins).toContain("http://localhost:8000");
    expect(origins).toContain("https://tiles.openfreemap.org");
    expect(new Set(origins).size).toBe(origins.length);
    for (const call of preconnect.mock.calls) {
      expect(call[1]).toEqual({ crossOrigin: "anonymous" });
    }
  });
});
