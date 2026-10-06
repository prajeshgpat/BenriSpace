import type { Page, Route } from "@playwright/test";

import { encodeScoreFile } from "../src/lib/scores/encode";

export const API = "https://api.e2e.test/v1";

// api/factors.py order, as the real file declares it.
const FILE_FACTORS = [
  "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience",
  "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation",
];
const WEB_FACTORS = [
  "grocery", "restaurant", "cafe", "bar", "gym", "shopping", "recreation",
  "gasConvenience", "transit", "airport", "traffic", "school", "emergencyCorridor",
];

const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";
function geohash(lat: number, lon: number, length = 6): string {
  let latR = [-90, 90];
  let lonR = [-180, 180];
  let out = "";
  let bits = 0;
  let ch = 0;
  let even = true;
  while (out.length < length) {
    const range = even ? lonR : latR;
    const value = even ? lon : lat;
    const mid = (range[0] + range[1]) / 2;
    if (value >= mid) {
      ch = (ch << 1) | 1;
      range[0] = mid;
    } else {
      ch <<= 1;
      range[1] = mid;
    }
    even = !even;
    if (++bits === 5) {
      out += BASE32[ch];
      bits = 0;
      ch = 0;
    }
  }
  latR = lonR = [];
  return out;
}

/** A synthetic grid over Manhattan: groceries are best in the west, transit in the east. */
export function syntheticScoreFile(): Buffer {
  const rows = new Map<string, { geohash: string; scores: (number | null)[] }>();
  for (let lat = 40.7; lat <= 40.8; lat += 0.0027) {
    for (let lon = -74.02; lon <= -73.92; lon += 0.0055) {
      const hash = geohash(lat, lon);
      const east = (lon + 74.02) / 0.1;
      const grocery = Math.round(100 - 90 * east);
      const transit = Math.round(10 + 90 * east);
      rows.set(hash, {
        geohash: hash,
        scores: FILE_FACTORS.map((k) => (k === "grocery" ? grocery : k === "transit" ? transit : 50)),
      });
    }
  }
  return Buffer.from(encodeScoreFile(FILE_FACTORS, [...rows.values()]));
}

const subScores = Object.fromEntries(WEB_FACTORS.map((k, i) => [k, 40 + i * 4]));

const score = {
  geoEntityId: "11111111-2222-3333-4444-555555555555",
  address: "350 5th Ave, New York, NY",
  latitude: 40.7484,
  longitude: -73.9857,
  compositeScore: 77,
  subScores,
  weightsVersion: "v2-handtuned",
  computedAt: "2026-10-01T00:00:00Z",
  neighborhood: "Midtown, Manhattan",
};

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(body),
  });

export interface MockOptions {
  /** Make /map/scores fail so the API fallback path is used. */
  noScoreFile?: boolean;
  /** Collects POST /feedback bodies. */
  feedback?: unknown[];
}

/** Answers every API and basemap request in the browser; nothing hits the network. */
export async function mockApi(page: Page, options: MockOptions = {}) {
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.fulfill({
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({ version: 8, sources: {}, layers: [] }),
    }),
  );
  // The build sets NEXT_PUBLIC_STATIC_URL to a host that does not exist, so
  // every run also proves the fallback: the manifest fetch fails and the app
  // works from the API alone.
  await page.route("https://static.e2e.test/**", (route) => route.abort("failed"));
  await page.route(`${API}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/v1/, "");
    if (request.method() === "OPTIONS") {
      return route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "*",
          "access-control-allow-methods": "GET,POST,OPTIONS",
        },
      });
    }
    switch (path) {
      case "/suggest":
        return json(route, {
          suggestions: [
            { label: "350 5th Ave, New York, NY", latitude: 40.7484, longitude: -73.9857 },
            { label: "350 5th Ave, Brooklyn, NY", latitude: 40.668, longitude: -73.985 },
          ],
        });
      case "/area":
        return json(route, { code: "area_not_found", message: "No area" }, 404);
      case "/score":
        return json(route, score);
      case "/area/explanation":
        return json(route, { explanation: "A well connected area.", source: "rules", areaId: null, priorities: [] });
      case "/map/scores":
        if (options.noScoreFile) return json(route, { code: "unavailable", message: "no" }, 503);
        return route.fulfill({
          status: 200,
          contentType: "application/octet-stream",
          headers: { "access-control-allow-origin": "*" },
          body: syntheticScoreFile(),
        });
      case "/map/cells":
        return json(route, {
          precision: 6, factors: WEB_FACTORS, weights: {}, weightsVersion: "v", truncated: false,
          geohashes: [geohash(40.75, -73.98)], scores: [64],
        });
      case "/map/top":
        return json(route, { factors: WEB_FACTORS, weights: {}, weightsVersion: "v", results: [] });
      case "/improve":
        return json(route, { suggestions: [], bestNearby: null, priorities: [] });
      case "/similar":
        return json(route, { minSeparationMi: 1, results: [], priorities: [] });
      case "/reverse":
        return json(route, { label: null, latitude: 40.75, longitude: -73.98 });
      case "/sources":
        return json(route, {
          sources: [
            {
              id: "osm", name: "OpenStreetMap points of interest", feeds: "Grocery, cafes, gyms",
              license: "ODbL 1.0", url: "https://www.openstreetmap.org/copyright",
              lastUpdated: new Date(Date.now() - 5.5 * 86_400_000).toISOString(),
            },
          ],
        });
      case "/feedback":
        options.feedback?.push(request.postDataJSON());
        return json(route, { ok: true });
      case "/triangulate": {
        const ring = [
          [-73.99, 40.74], [-73.97, 40.74], [-73.97, 40.76], [-73.99, 40.76], [-73.99, 40.74],
        ];
        const shape = {
          mode: "transit", minutes: 20, method: "network", cellCount: 6, areaSqMi: 2.4,
          geometry: { type: "MultiPolygon", coordinates: [[ring]] },
        };
        return json(route, {
          results: [
            { geoEntityId: "11111111-2222-3333-4444-555555555556", address: "40.7500,-73.9800", latitude: 40.75, longitude: -73.98, compositeScore: 74 },
            { geoEntityId: "11111111-2222-3333-4444-555555555557", address: "40.7450,-73.9750", latitude: 40.745, longitude: -73.975, compositeScore: 68 },
          ],
          isochrones: [shape, shape],
          combined: shape,
        });
      }
      case "/chat":
        return json(route, { reply: "Try the Upper West Side.", results: [], sources: [] });
      default:
        return json(route, { code: "not_found", message: path }, 404);
    }
  });
}
