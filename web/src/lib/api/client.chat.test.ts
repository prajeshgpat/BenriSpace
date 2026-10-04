import { describe, expect, it, vi } from "vitest";

import { jsonResponse } from "@/test/fixtures";

import { CHAT_TIMEOUT_MS, createApiClient, prepareChatTurns } from "./client";
import { ApiError } from "./errors";

const BASE_URL = "http://api.test/v1";

function clientReturning(response: Response) {
  const fetchMock = vi.fn<typeof fetch>(async () => response);
  return { fetchMock, client: createApiClient({ baseUrl: BASE_URL, fetch: fetchMock }) };
}

const REPLY = {
  reply: "Darien looks best.",
  results: [
    { label: "Darien, CT", latitude: 41.07, longitude: -73.47, score: 87, weeklyMinutes: 274, why: "Short trips." },
    { label: "", latitude: 1, longitude: 2, why: "dropped: no label" },
    { label: "No coordinates", why: "dropped" },
  ],
  sources: [{ tool: "optimize_location", summary: "3 areas" }, { tool: 5 }],
  limited: true,
};

describe("chat", () => {
  it("POSTs the last turns and context as JSON and parses the reply", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(REPLY));

    const result = await client.chat(
      [{ role: "user", content: " hi " }],
      { address: "5 Main St", factors: ["grocery"] },
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE_URL}/chat`);
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({
      messages: [{ role: "user", content: "hi" }],
      context: { address: "5 Main St", factors: ["grocery"] },
    });
    expect(result).toEqual({
      reply: "Darien looks best.",
      results: [REPLY.results[0]],
      sources: [REPLY.sources[0]],
      limited: true,
    });
  });

  it("omits an empty context and defaults limited to false", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse({ reply: "ok", results: [], sources: [] }));
    const result = await client.chat([{ role: "user", content: "hi" }]);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      messages: [{ role: "user", content: "hi" }],
    });
    expect(result.limited).toBe(false);
  });

  it("uses the longer chat timeout", async () => {
    const spy = vi.spyOn(AbortSignal, "timeout");
    const { client } = clientReturning(jsonResponse(REPLY));
    await client.chat([{ role: "user", content: "hi" }]);
    expect(spy).toHaveBeenCalledWith(CHAT_TIMEOUT_MS);
  });

  it("rejects a malformed reply as invalid-response", async () => {
    const { client } = clientReturning(jsonResponse({ results: [] }));
    await expect(client.chat([{ role: "user", content: "hi" }])).rejects.toMatchObject({
      kind: "invalid-response",
    });
  });

  it.each([
    [429, { code: "rate_limited", message: "limit" }, "rate-limited"],
    [503, { code: "chat_unavailable", message: "down" }, "server"],
    [400, { code: "invalid_request", message: "bad" }, "invalid-request"],
  ])("maps HTTP %i to %s", async (status, body, kind) => {
    const { client } = clientReturning(jsonResponse(body, status));
    await expect(client.chat([{ role: "user", content: "hi" }])).rejects.toMatchObject({ kind });
  });
});

describe("prepareChatTurns", () => {
  it("keeps the last six turns, cut to 2000 characters, starting with a user turn", () => {
    const turns = Array.from({ length: 9 }, (_, i) => ({
      role: i % 2 === 0 ? ("user" as const) : ("assistant" as const),
      content: `m${i}`,
    }));
    turns[8].content = "x".repeat(3000);
    const out = prepareChatTurns(turns);
    expect(out[0].role).toBe("user");
    expect(out.length).toBeLessThanOrEqual(6);
    expect(out.at(-1)?.content).toHaveLength(2000);
  });

  it("rejects an empty conversation or one not ending with the user", () => {
    for (const turns of [[], [{ role: "assistant" as const, content: "hi" }], [{ role: "user" as const, content: "  " }]]) {
      expect(() => prepareChatTurns(turns)).toThrow(ApiError);
    }
  });
});
