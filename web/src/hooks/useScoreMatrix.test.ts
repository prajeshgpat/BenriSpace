import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { encodeScoreFile } from "@/lib/scores/encode";
import { resetStaticCache } from "@/lib/static/manifest";

import { loadScoreMatrix } from "./useScoreMatrix";

const BASE = "https://tiles.example.com";
const FACTORS = ["grocery", "gym"];

function file(version: string): ArrayBuffer {
  return encodeScoreFile(FACTORS, [{ geohash: "dr5ru7", scores: [60, 70] }], version);
}

const manifest = { format: 1, scores: { path: "scores/v.abc.bin" } };

function stubFetch(handler: (url: string) => Response | Promise<Response>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => handler(String(input)));
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => resetStaticCache());
afterEach(() => vi.unstubAllGlobals());

describe("loadScoreMatrix with a static origin", () => {
  it("reads the score file from the manifest and never calls the API", async () => {
    stubFetch((url) =>
      url.endsWith("manifest.json")
        ? new Response(JSON.stringify(manifest))
        : new Response(file("from-static")),
    );
    const client = { getMapScores: vi.fn(async () => file("from-api")) };
    const matrix = await loadScoreMatrix(client, BASE);
    expect(matrix.header.version).toBe("from-static");
    expect(client.getMapScores).not.toHaveBeenCalled();
  });

  it.each([
    ["manifest missing", () => new Response("", { status: 404 })],
    ["network or CORS error", () => Promise.reject(new TypeError("blocked"))],
    [
      "undecodable file",
      (url: string) =>
        url.endsWith("manifest.json")
          ? new Response(JSON.stringify(manifest))
          : new Response(new Uint8Array([1, 2, 3])),
    ],
    [
      "no scores entry",
      (url: string) =>
        url.endsWith("manifest.json") ? new Response(JSON.stringify({ format: 1 })) : new Response(""),
    ],
  ])("falls back to the API: %s", async (_name, handler) => {
    stubFetch(handler as (url: string) => Response | Promise<Response>);
    const client = { getMapScores: vi.fn(async () => file("from-api")) };
    const matrix = await loadScoreMatrix(client, BASE);
    expect(matrix.header.version).toBe("from-api");
    expect(client.getMapScores).toHaveBeenCalledTimes(1);
  });
});

describe("loadScoreMatrix without one", () => {
  it("is exactly the API download and touches no static URL", async () => {
    const fetchMock = stubFetch(() => new Response(""));
    const client = { getMapScores: vi.fn(async () => file("from-api")) };
    const matrix = await loadScoreMatrix(client, undefined);
    expect(matrix.header.version).toBe("from-api");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
