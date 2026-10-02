import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { jsonResponse, liveExplanationBody, liveScoreBody } from "@/test/fixtures";

import { ScoreExplorer } from "./ScoreExplorer";

const navigation = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

let pushState: MockInstance<History["pushState"]>;

type Responder = (url: string) => Response | Promise<Response>;

function renderExplorer(search: string, respond: Responder) {
  navigation.search = search;
  const fetchMock = vi.fn<typeof fetch>(async (input) => respond(String(input)));
  const client = createApiClient({ baseUrl: "http://api.test/v1", fetch: fetchMock });
  return { fetchMock, client, ...render(<ScoreExplorer client={client} />) };
}

const lookupStatus = () =>
  screen.getAllByRole("status").find((el) => el.textContent !== "")!;

const suggestionBody = {
  suggestions: [
    { label: "350 5th Avenue, New York, NY", latitude: 40.7484, longitude: -73.9857 },
    { label: "350 5th Street, Brooklyn, NY", latitude: 40.67, longitude: -73.98 },
  ],
};

const liveApi: Responder = (url) =>
  url.includes("/explanation")
    ? jsonResponse(liveExplanationBody)
    : jsonResponse(liveScoreBody);

beforeEach(() => {
  pushState = vi.spyOn(window.history, "pushState").mockImplementation(() => {});
  navigation.search = "";
});

describe("ScoreExplorer", () => {
  it("shows the empty state and makes no request without an address", () => {
    const { fetchMock } = renderExplorer("", liveApi);

    expect(screen.getByRole("heading", { name: /what you.ll see/i })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("navigates to a shareable URL when an address is submitted", async () => {
    const user = userEvent.setup();
    renderExplorer("", liveApi);

    await user.type(screen.getByRole("combobox", { name: "Address" }), "  350 5th Ave,  New York ");
    await user.click(screen.getByRole("button", { name: "Get score" }));

    expect(pushState).toHaveBeenCalledWith(null, "", "/?address=350+5th+Ave%2C+New+York");
  });

  it("validates before navigating and points the field at the message", async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderExplorer("", liveApi);

    await user.click(screen.getByRole("button", { name: "Get score" }));

    const input = screen.getByRole("combobox", { name: "Address" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an address to score.");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/Enter an address to score\./);
    expect(input).toHaveFocus();
    expect(pushState).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(input, "3");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejects an invalid address arriving via the URL without calling the API", () => {
    const { fetchMock } = renderExplorer("address=a", liveApi);

    expect(screen.getByRole("alert")).toHaveTextContent(/at least 3 characters/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads and renders a result from the address in the URL", async () => {
    const { fetchMock } = renderExplorer(
      "address=350+5th+Ave%2C+New+York%2C+NY",
      liveApi,
    );

    expect(screen.getByTestId("result-skeleton")).toBeInTheDocument();
    expect(lookupStatus()).toHaveTextContent(
      "Scoring 350 5th Ave, New York, NY…",
    );
    expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue(
      "350 5th Ave, New York, NY",
    );

    expect(
      await screen.findByRole("heading", { level: 2, name: "350 5th Ave, New York, NY" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("composite-score")).toHaveTextContent("63");
    expect(screen.getAllByText("No data")).toHaveLength(10);
    expect(
      await screen.findByText(/strongest factor is airport drive time/),
    ).toBeInTheDocument();
    expect(lookupStatus()).toHaveTextContent(
      "350 5th Ave, New York, NY scores 63 out of 100, Good.",
    );
    expect(document.title).toBe("350 5th Ave, New York, NY · BenriSpace");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows the out-of-coverage state for a 404, with no retry", async () => {
    renderExplorer("address=1600+Pennsylvania+Ave%2C+Washington+DC", () =>
      jsonResponse({ code: "not_found", message: "No geo entity", upgradeUrl: null }, 404),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That address is outside our coverage");
    expect(alert).toHaveTextContent("1600 Pennsylvania Ave, Washington DC");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("composite-score")).not.toBeInTheDocument();
  });

  it("shows the address-not-found state when geocoding fails", async () => {
    renderExplorer("address=zzqqxx", () =>
      jsonResponse({ code: "unresolvable_address", message: "Could not geocode" }, 400),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn't find that address",
    );
  });

  it("shows the network-error state and recovers on retry", async () => {
    const user = userEvent.setup();
    let online = false;
    const { fetchMock } = renderExplorer("address=350+5th+Ave", (url) => {
      if (!online) throw new TypeError("Failed to fetch");
      return liveApi(url);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Can't reach BenriSpace right now",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    online = true;
    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(screen.getByTestId("composite-score")).toHaveTextContent("63"),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("re-runs the lookup when the current address is submitted again", async () => {
    const user = userEvent.setup();
    const { fetchMock } = renderExplorer("address=350+5th+Ave", liveApi);
    await screen.findByText(/strongest factor/);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await user.click(screen.getByRole("button", { name: "Get score" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(pushState).not.toHaveBeenCalled();
  });

  it("resyncs the field when the URL address changes underneath it", async () => {
    const { client, rerender } = renderExplorer("address=350+5th+Ave", liveApi);
    const input = screen.getByRole("combobox", { name: "Address" });
    expect(input).toHaveValue("350 5th Ave");

    navigation.search = "address=Hoboken+Terminal";
    rerender(<ScoreExplorer client={client} />);

    expect(screen.getByRole("combobox", { name: "Address" })).toBe(input);
    expect(input).toHaveValue("Hoboken Terminal");
    await screen.findByRole("heading", { level: 2, name: "Hoboken Terminal" });
  });

  it("offers example addresses as real links that search in place", async () => {
    const user = userEvent.setup();
    renderExplorer("", liveApi);
    const link = screen.getByRole("link", { name: "350 5th Ave, New York, NY" });

    expect(link).toHaveAttribute("href", "/?address=350+5th+Ave%2C+New+York%2C+NY");

    await user.click(link);

    expect(pushState).toHaveBeenCalledWith(
      null,
      "",
      "/?address=350+5th+Ave%2C+New+York%2C+NY",
    );
  });
  describe("autocomplete", () => {
    const withSuggestions: Responder = (url) =>
      url.includes("/suggest") ? jsonResponse(suggestionBody) : liveApi(url);

    it("selecting a suggestion navigates by coordinates, skipping geocoding", async () => {
      const user = userEvent.setup();
      renderExplorer("", withSuggestions);
      const input = screen.getByRole("combobox", { name: "Address" });

      await user.type(input, "350 5th");
      const option = await screen.findByRole("option", { name: /350 5th Avenue/ });
      await user.click(option);

      expect(pushState).toHaveBeenCalledWith(
        null,
        "",
        "/?address=350+5th+Avenue%2C+New+York%2C+NY&lat=40.7484&lon=-73.9857",
      );
      expect(input).toHaveValue("350 5th Avenue, New York, NY");
      expect(screen.queryByRole("option")).not.toBeInTheDocument();
    });

    it("scores a shared coordinate URL without geocoding", async () => {
      const { fetchMock } = renderExplorer(
        "address=350+5th+Avenue%2C+New+York%2C+NY&lat=40.7484&lon=-73.9857",
        withSuggestions,
      );

      expect(await screen.findByTestId("composite-score")).toBeInTheDocument();
      const urls = fetchMock.mock.calls.map(([url]) => String(url));
      expect(urls).toContain("http://api.test/v1/score?lat=40.7484&lon=-73.9857");
      expect(urls.some((url) => url.includes("address="))).toBe(false);
      expect(urls.some((url) => url.includes("/suggest"))).toBe(false);
      expect(screen.getByRole("combobox", { name: "Address" })).toHaveValue(
        "350 5th Avenue, New York, NY",
      );
      expect(
        screen.getByRole("heading", { level: 2, name: "350 5th Avenue, New York, NY" }),
      ).toBeInTheDocument();
    });

    it("labels a coordinate-only URL with the coordinates", async () => {
      renderExplorer("lat=40.7484&lon=-73.9857", withSuggestions);
      expect(
        await screen.findByRole("heading", { level: 2, name: "40.7484, -73.9857" }),
      ).toBeInTheDocument();
    });

    it("falls back to the address when the coordinates are invalid", async () => {
      const { fetchMock } = renderExplorer("address=350+5th+Ave&lat=999&lon=abc", liveApi);
      await screen.findByTestId("composite-score");
      expect(String(fetchMock.mock.calls[0][0])).toContain("/score?address=350+5th+Ave");
    });

    it("still searches typed text with Enter when suggestions fail", async () => {
      const user = userEvent.setup();
      renderExplorer("", (url) =>
        url.includes("/suggest")
          ? jsonResponse({ code: "suggest_unavailable", message: "down" }, 503)
          : liveApi(url),
      );
      const input = screen.getByRole("combobox", { name: "Address" });

      await user.type(input, "350 5th Ave");
      await waitFor(() => expect(screen.queryByRole("option")).not.toBeInTheDocument());
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      await user.keyboard("{Enter}");

      expect(pushState).toHaveBeenCalledWith(null, "", "/?address=350+5th+Ave");
    });

    it("does not look anything up when the field is filled from the URL", async () => {
      const { fetchMock } = renderExplorer("address=350+5th+Ave", withSuggestions);
      await screen.findByTestId("composite-score");
      await new Promise((resolve) => setTimeout(resolve, 350));
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/suggest"))).toBe(false);
    });
  });
});
