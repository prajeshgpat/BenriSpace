import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

import { OUTSIDE_COVERAGE_MESSAGE } from "@/lib/geolocation";

import { HomeSearch } from "./HomeSearch";

type GetCurrentPosition = Geolocation["getCurrentPosition"];

const MANHATTAN = { latitude: 40.74918, longitude: -73.98503 };
const KANSAS = { latitude: 39.0997, longitude: -94.5786 };

function installGeolocation(impl: GetCurrentPosition) {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { getCurrentPosition: vi.fn<GetCurrentPosition>(impl) },
  });
}

const positionAt =
  (coords: { latitude: number; longitude: number }): GetCurrentPosition =>
  (success) =>
    success({ coords, timestamp: 0 } as GeolocationPosition);

const failWith =
  (code: number): GetCurrentPosition =>
  (_success, error) =>
    error?.({ code, message: "" } as GeolocationPositionError);

function renderSearch() {
  render(
    <HomeSearch
      suggestClient={{ suggestAddresses: vi.fn().mockResolvedValue([]) }}
    />,
  );
  return screen.getByRole("button", { name: "Use my current location" });
}

describe("HomeSearch current location", () => {
  beforeEach(() => {
    push.mockReset();
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: true,
    });
  });
  afterEach(() => {
    Reflect.deleteProperty(window, "isSecureContext");
    Reflect.deleteProperty(navigator, "geolocation");
  });

  it("opens the app on the coordinates inside coverage", async () => {
    installGeolocation(positionAt(MANHATTAN));
    await userEvent.click(renderSearch());
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    const url = new URL(push.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/app");
    expect(url.searchParams.get("address")).toBe("Your location");
    expect(Number(url.searchParams.get("lat"))).toBeCloseTo(
      MANHATTAN.latitude,
      2,
    );
    expect(Number(url.searchParams.get("lon"))).toBeCloseTo(
      MANHATTAN.longitude,
      2,
    );
  });

  it.each([
    [1, /denied|blocked|permission/i],
    [3, /time|took too long/i],
  ])(
    "shows a message and stays put on error code %i",
    async (code, message) => {
      installGeolocation(failWith(code));
      await userEvent.click(renderSearch());
      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(push).not.toHaveBeenCalled();
    },
  );

  it("explains and does not navigate outside coverage", async () => {
    installGeolocation(positionAt(KANSAS));
    await userEvent.click(renderSearch());
    expect(
      await screen.findByText(OUTSIDE_COVERAGE_MESSAGE),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("disables the button with a description when unsupported", async () => {
    Reflect.deleteProperty(navigator, "geolocation");
    const button = renderSearch();
    await waitFor(() => expect(button).toBeDisabled());
    const note = document.getElementById(
      button.getAttribute("aria-describedby")!,
    );
    expect(note).toHaveTextContent(/.+/);
  });
});
