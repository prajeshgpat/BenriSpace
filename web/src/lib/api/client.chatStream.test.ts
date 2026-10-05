import { describe, expect, it, vi } from "vitest";

import { jsonResponse } from "@/test/fixtures";

import { createApiClient, splitSseFrames } from "./client";

const BASE_URL = "http://api.test/v1";
const STREAM_URL = "https://stream.test/chat";
const TURNS = [{ role: "user" as const, content: "hi" }];
const REPLY = { reply: "Darien looks best.", results: [], sources: [] };

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function sse(chunks: string[], status = 200, type = "text/event-stream"): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": type } });
}

function setup(streamed: () => Response | Promise<Response>, plain = () => jsonResponse(REPLY)) {
  const fetchMock = vi.fn<typeof fetch>(async (input) =>
    String(input) === STREAM_URL ? streamed() : plain(),
  );
  const client = createApiClient({ baseUrl: BASE_URL, fetch: fetchMock, chatStreamUrl: STREAM_URL });
  return { client, fetchMock };
}

describe("splitSseFrames", () => {
  it("returns whole frames and keeps the unfinished tail", () => {
    const { frames, rest } = splitSseFrames(
      ': open\n\nevent: status\ndata: {"text":"a"}\n\nevent: rep',
    );
    expect(frames).toEqual([{ event: "status", data: '{"text":"a"}' }]);
    expect(rest).toBe("event: rep");
  });
});

describe("streaming chat", () => {
  it("reports status frames and resolves with the reply, even split across chunks", async () => {
    const text = frame("status", { text: "Searching areas" }) + frame("reply", REPLY);
    const { client, fetchMock } = setup(() => sse([text.slice(0, 20), text.slice(20)]));
    const statuses: string[] = [];
    const result = await client.chat(TURNS, {}, { onStatus: (t) => statuses.push(t) });
    expect(statuses).toEqual(["Searching areas"]);
    expect(result.reply).toBe("Darien looks best.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe(STREAM_URL);
  });

  it("uses plain /chat when no one listens for status", async () => {
    const { client, fetchMock } = setup(() => sse([]));
    await client.chat(TURNS);
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE_URL}/chat`);
  });

  it("falls back to /chat when the endpoint is missing, wrong, or unreachable", async () => {
    for (const streamed of [
      () => jsonResponse({}, 404),
      () => sse([frame("reply", REPLY)], 200, "application/json"),
      () => Promise.reject(new TypeError("offline")),
      () => sse([frame("status", { text: "x" })]),
    ]) {
      const { client, fetchMock } = setup(streamed);
      const result = await client.chat(TURNS, {}, { onStatus: () => {} });
      expect(result.reply).toBe("Darien looks best.");
      expect(String(fetchMock.mock.calls.at(-1)?.[0])).toBe(`${BASE_URL}/chat`);
    }
  });

  it("surfaces a server error frame and a rate limit without a second request", async () => {
    const error = setup(() =>
      sse([frame("error", { status: 429, code: "rate_limited", message: "limit" })]),
    );
    await expect(error.client.chat(TURNS, {}, { onStatus: () => {} })).rejects.toMatchObject({
      kind: "rate-limited",
    });
    expect(error.fetchMock).toHaveBeenCalledTimes(1);

    const limited = setup(() => jsonResponse({ code: "rate_limited", message: "limit" }, 429));
    await expect(limited.client.chat(TURNS, {}, { onStatus: () => {} })).rejects.toMatchObject({
      kind: "rate-limited",
    });
    expect(limited.fetchMock).toHaveBeenCalledTimes(1);
  });
});
