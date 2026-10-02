# BenriSpace API

BenriSpace scores how convenient a location is to live at, 0 to 100, for the New York metro area (NYC, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County, CT).

- **Base URL:** `https://api.benrispace.com/v1`
- **Interactive docs (Swagger UI):** <https://api.benrispace.com/docs>
- **Machine-readable spec:** <https://api.benrispace.com/openapi.json> (the source contract lives in [`contracts/openapi.yaml`](../contracts/openapi.yaml))

| Endpoint | Purpose | Status |
| --- | --- | --- |
| `GET /score` | Score for one address or coordinate | live |
| `GET /score/{geoEntityId}/explanation` | Plain-language explanation of a score | live |
| `POST /triangulate` | Best locations that satisfy several commute anchors | live (placeholder geometry, see below) |
| `GET /suggest` | Address autocomplete | available after the next deploy |
| `GET /map/cells` | Composite score per map cell for a chosen set of factors | available after the next deploy |
| `GET /map/top` | Best, well-separated areas for a chosen set of factors | available after the next deploy |

Examples for `/score`, `/score/{id}/explanation` and `/triangulate` below are real responses from the production API. Examples for the three newer endpoints are real responses from the same code running against the production database; they are not reachable on `api.benrispace.com` until the next deploy.

## Conventions

- **Authentication:** none today. Phase 4 will add API keys and usage tiers (an `Authorization: Bearer ...` or `X-API-Key` header).
- **JSON, camelCase:** every field name is camelCase (`compositeScore`, `geoEntityId`, `gasStation`).
- **Errors** always have the same shape, with an HTTP status that matches:

  ```json
  { "code": "invalid_request", "message": "bbox is empty or inverted: need minLon < maxLon and minLat < maxLat" }
  ```

  `code` is stable and meant for programs; `message` is for humans and may change.
- **`null` means "not measured", never 0.** A sub-score can be `null` when the underlying data does not exist for that spot yet. Treat it as unknown. Composites ignore `null` factors rather than counting them as zero.
- **CORS:** browsers may call the API only from `https://benrispace.com`, `https://www.benrispace.com` and `http://localhost:3000`. From any other origin the browser will block the response. Server-side clients (curl, Python, Node) are not affected by CORS.
- **Caching:** `/suggest`, `/map/cells` and `/map/top` send `Cache-Control: public, max-age=300`. Scores only change when the weekly data refresh runs.
- **Rate limiting:** the API Gateway currently allows a steady 10 requests per second with bursts of 20, across all callers. Beyond that you get `429 Too Many Requests` (from API Gateway, not the application, so the body is not in the error shape above). Per-user quotas arrive with API keys.

## What a score means

- Scores run from **0 to 100, and higher is always better**. Factors where less is better (gas stations nearby, traffic, emergency-vehicle corridors, airport drive time) are already inverted, so a high `gasStation` score means "far from gas stations".
- Scores are **relative within a metro area**, not absolute. Each factor is min-max normalized across all cells in the same metro area (for example `nyc` or `northern_nj`), so 100 means "best in its metro area for this factor" and 0 means "worst". A suburban cell is compared with other suburban cells in its own area, not with Manhattan.
- **No location scores 100 on everything.** Factors pull in opposite directions: the spots with the best transit, cafes and groceries are dense, and dense places have more gas stations, traffic and emergency-vehicle noise. In the example below, 350 5th Avenue scores 100 on transit but 10 on distance from gas stations. A composite near 80 is exceptional.
- The **composite** (`compositeScore`) is a weighted average of the eleven sub-scores. Default weights (version `v1-handtuned`): grocery 1.5, gym 1.0, cafe 1.0, gasStation 1.0, convenienceStore 0.75, transit 1.5, school 1.5, road 1.0, emergencyCorridor 0.5, airport 0.75, trailPopularity 1.25. `/map/cells` and `/map/top` let you choose your own factors and weights.
- `weightsVersion` tells you which set of stored scores you are looking at.

### The eleven factors

| Key | Meaning of a high score |
| --- | --- |
| `grocery` | Grocery stores close by |
| `gym` | Gyms close by |
| `cafe` | Cafes close by |
| `gasStation` | Far from gas stations |
| `convenienceStore` | Far from convenience stores |
| `transit` | Close to frequent transit stops |
| `school` | Schools close by and well rated |
| `road` | Light traffic and congestion nearby |
| `emergencyCorridor` | Far from emergency-vehicle corridors |
| `airport` | Short drive to a major airport |
| `trailPopularity` | Running and walking trails close by |

## Geohash cells

The metro area is divided into a grid of **geohash6** cells, roughly 1.2 km by 0.6 km. Every score belongs to one cell. `/map/cells` identifies cells by their geohash string (for example `dr5ru0`); with `precision=5` the cells are about 4.9 km by 4.9 km (`dr5ru`), and each one is the average of the finer cells inside it.

A geohash is a base-32 string (alphabet `0123456789bcdefghjkmnpqrstuvwxyz`) in which each character narrows a latitude/longitude rectangle; a longer string is a smaller rectangle, and a cell's prefix is the larger cell containing it. To get a cell's rectangle, decode it:

```js
const B32 = "0123456789bcdefghjkmnpqrstuvwxyz";

function decodeGeohash(gh) {
  let lat = [-90, 90], lon = [-180, 180], evenBit = true;
  for (const ch of gh) {
    const v = B32.indexOf(ch);
    for (const mask of [16, 8, 4, 2, 1]) {
      const r = evenBit ? lon : lat;
      const mid = (r[0] + r[1]) / 2;
      if (v & mask) r[0] = mid; else r[1] = mid;
      evenBit = !evenBit;
    }
  }
  return { minLat: lat[0], maxLat: lat[1], minLon: lon[0], maxLon: lon[1],
           lat: (lat[0] + lat[1]) / 2, lon: (lon[0] + lon[1]) / 2 };
}

decodeGeohash("dr5ru0");
// { minLat: 40.7373046875, maxLat: 40.7427978515625,
//   minLon: -74.00390625,  maxLon: -73.992919921875,
//   lat: 40.74005126953125, lon: -73.9984130859375 }
```

In Python, `pip install pygeohash` and use `pygeohash.decode("dr5ru0")`, which returns the cell centre. Note that the `latitude`/`longitude` returned by `/score` and `/map/top` are the grid point stored for that cell, which lies inside the cell but is not exactly its centre.

---

## `GET /score`

Score for one place. Give either `address`, or `lat` and `lon`, not both.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `address` | string | one of address / lat+lon | Free-text address. Geocoded server-side with OpenStreetMap Nominatim. |
| `lat` | number | with `lon` | Latitude. Skips geocoding; use this with a `/suggest` result. |
| `lon` | number | with `lat` | Longitude. |

The point is snapped to its geohash6 cell; if that exact cell is not in the grid, the nearest covered cell within about 3 km is used.

```bash
curl "https://api.benrispace.com/v1/score?lat=40.7484&lon=-73.9857"
```

```json
{
  "geoEntityId": "21c5d4bd-e66e-423b-8f4c-8e569604f187",
  "address": "40.74920,-73.98500",
  "latitude": 40.7492000000001,
  "longitude": -73.9850000000001,
  "compositeScore": 76.645099179088,
  "subScores": {
    "grocery": 98.5056656164793,
    "gym": 98.2984870221148,
    "cafe": 99.4514400180914,
    "gasStation": 10.2361735211859,
    "convenienceStore": 1.84043553461295,
    "transit": 99.9189755928139,
    "school": 77.1920607191068,
    "road": 84.8767104736265,
    "emergencyCorridor": 95.0488509733435,
    "airport": 62.7906976744186,
    "trailPopularity": 78.6354208265756
  },
  "weightsVersion": "v1-handtuned",
  "computedAt": "2026-09-30T15:02:10.262476Z"
}
```

`address` is the cell's formatted address when one is stored, otherwise its `"lat,lon"` string (as here). The coordinates are those of the matched grid cell, not necessarily the point you sent.

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Neither or both of `address` and `lat`/`lon` given; malformed numbers |
| 400 | `unresolvable_address` | The address could not be geocoded |
| 404 | `not_found` | The location is outside the covered area, or has no score yet |

```json
{ "code": "not_found", "message": "No geo entity within ingestion coverage for this location." }
```

---

## `GET /score/{geoEntityId}/explanation`

A short plain-language explanation of one score: the strongest factor, the weakest, and the rest. Currently generated from a template; an LLM-written explanation may replace it later without changing the shape.

| Parameter | In | Type | Description |
| --- | --- | --- | --- |
| `geoEntityId` | path | UUID | The `geoEntityId` from a `/score` response |

```bash
curl "https://api.benrispace.com/v1/score/21c5d4bd-e66e-423b-8f4c-8e569604f187/explanation"
```

```json
{
  "geoEntityId": "21c5d4bd-e66e-423b-8f4c-8e569604f187",
  "explanation": "This location's strongest factor is transit access (100/100). Its weakest factor is distance from convenience stores (2/100). Other factors: cafe access 99/100, grocery access 99/100, gym access 98/100, distance from emergency-vehicle corridors 95/100, road and traffic conditions 85/100, access to popular running and walking trails 79/100, school quality and proximity 77/100, airport drive time 63/100, distance from gas stations 10/100.",
  "computedAt": "2026-09-30T15:02:10.262476Z"
}
```

Errors: `400 invalid_request` if the id is not a UUID, `404 not_found` if no score exists for it.

---

## `POST /triangulate`

Given up to four anchors (workplace, gym, family, ...) with a maximum travel time each, return the best-scoring locations reachable from all of them (`intersect`) or any of them (`union`), ranked by composite score.

**This is a placeholder.** There is no routing engine yet, so each anchor's reachable area is a straight-line circle, with radius = `maxTravelMinutes` x an assumed average speed for the mode (drive 40 km/h, transit 25 km/h, walk 4.8 km/h). Ignoring rivers, bridges, highways and real transit lines, it can be off by a lot, particularly across water. Real isochrones will replace it; the request and response shapes are not expected to change.

Request body (JSON):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `anchors` | array, 1-4 items | yes | Places you need to reach |
| `anchors[].label` | string | yes | Your name for the anchor |
| `anchors[].address` | string | one of address / lat+lon | Geocoded server-side |
| `anchors[].latitude`, `anchors[].longitude` | number | one of address / lat+lon | Coordinates |
| `anchors[].maxTravelMinutes` | integer | no | Default 20 |
| `anchors[].mode` | `drive` \| `transit` \| `walk` | no | Default `drive` |
| `combineMode` | `intersect` \| `union` | no | Default `intersect` |
| `limit` | integer | no | Results returned, default 50 |

```bash
curl -X POST "https://api.benrispace.com/v1/triangulate" \
  -H "Content-Type: application/json" \
  -d '{
    "anchors": [
      {"label": "Work", "latitude": 40.7527, "longitude": -73.9772, "maxTravelMinutes": 20, "mode": "transit"},
      {"label": "Gym",  "latitude": 40.7411, "longitude": -73.9897, "maxTravelMinutes": 15, "mode": "walk"}
    ],
    "combineMode": "intersect",
    "limit": 3
  }'
```

```json
{
  "results": [
    {
      "geoEntityId": "4605d6c0-f67a-4d02-b944-e024a34469ec",
      "address": "40.73300,-73.98500",
      "latitude": 40.7330000000001,
      "longitude": -73.9850000000001,
      "compositeScore": 77.4106029215863
    },
    {
      "geoEntityId": "0dc8e60e-0732-4723-946c-6807e293e8d3",
      "address": "40.74380,-73.99600",
      "latitude": 40.7438000000001,
      "longitude": -73.9960000000001,
      "compositeScore": 77.1074770164484
    },
    {
      "geoEntityId": "a48dc9c5-7844-49a5-9ff2-5d9f9b329894",
      "address": "40.73840,-73.99600",
      "latitude": 40.7384000000001,
      "longitude": -73.9960000000001,
      "compositeScore": 77.093630662023
    }
  ]
}
```

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Body fails validation (for example zero or more than four anchors) |
| 400 | `invalid_anchor` | An anchor has neither coordinates nor a geocodable address |

```json
{ "code": "invalid_anchor", "message": "Anchor 'x' needs a resolvable address or lat/lon." }
```

---

## `GET /suggest`

*Available after the next deploy.*

Address autocomplete for a search box. Returns up to `limit` places for what the user has typed so far, restricted to the covered area and biased toward the middle of the metro. Pass a suggestion's `latitude`/`longitude` straight to `GET /score?lat=&lon=`, which skips geocoding.

Suggestions come from [Photon](https://photon.komoot.io), a geocoder built on OpenStreetMap data, proxied so browsers never talk to it directly. Results are cleaned up before you see them: labels are built as `house number + street, city, state` (NY, NJ, CT, PA abbreviated), point-of-interest names at an address are replaced by the address itself, and duplicate labels or points within 25 m of each other are merged. A query that starts with a digit lists addresses before streets and landmarks. The same query is cached on the server for 10 minutes.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `q` | string | yes | Text typed so far. At least 3 characters after trimming whitespace; at most 200. |
| `limit` | integer | no | 1 to 10, default 5 |

```bash
curl "http://localhost:8000/v1/suggest?q=hoboken&limit=5"
```

```json
{
  "suggestions": [
    { "label": "Hoboken, NJ", "latitude": 40.7433066, "longitude": -74.0323752 },
    { "label": "Hoboken Terminal, Hoboken, NJ", "latitude": 40.7349447, "longitude": -74.0273829 },
    { "label": "Hoboken - World Trade Center, New York, NY", "latitude": 40.713043, "longitude": -74.0137545 },
    { "label": "800 Clinton Street, Hoboken, NJ", "latitude": 40.7476351, "longitude": -74.0330646 },
    { "label": "500 Park Avenue, Hoboken, NJ", "latitude": 40.7428824, "longitude": -74.0322821 }
  ]
}
```

The list can be shorter than `limit`, or empty, when the provider has few distinct matches in the covered area (`350 5th ave` returns the single address `350 5th Avenue, New York, NY`).

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | `q` missing or shorter than 3 characters; `limit` outside 1-10 |
| 503 | `suggest_unavailable` | The provider timed out (3 s), returned an error, or sent something unreadable |

On a 503, fall back to plain-text search (`GET /score?address=...`) rather than showing an error. Error responses are not cached.

---

## `GET /map/cells`

*Available after the next deploy.*

Composite score for every grid cell inside a map viewport, calculated for the factors and weights you choose. It is a weighted average of the stored sub-scores (not a recalculation from raw data), so it is cheap to call whenever the user toggles a filter.

For each cell, the composite uses only the selected factors that are not `null` for that cell, so the denominator counts only the weights of factors that have data; cells where every selected factor is `null` are left out.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `bbox` | string | yes | Viewport as `minLon,minLat,maxLon,maxLat`. Cells whose grid point lies inside are returned. |
| `precision` | integer | no | `6` (default, about 1.2 x 0.6 km cells) or `5` (about 4.9 x 4.9 km; the mean of the finer cells). Use 5 when zoomed out. |
| `factors` | string | no | Comma-separated factor keys to include, for example `transit,cafe`. Omit for all eleven. Must not be empty if present. |
| `weights` | string | no | Overrides as `factor:number`, comma-separated, for example `transit:2,cafe:0.5`. Numbers must be greater than 0 (to drop a factor, leave it out of `factors`). Factors without an override use their default weight. Overrides for factors not in `factors` are ignored. |
| `limit` | integer | no | 1 to 20000, default 8000. `truncated` is true when more cells matched. |

Response fields: `precision`, `factors` (the factors actually used), `weights` (the weight applied to each), `weightsVersion`, `count`, `truncated`, and two parallel arrays, `geohashes` and `scores`, where `scores[i]` belongs to `geohashes[i]`. Scores are rounded to one decimal. Cells are returned in geohash order.

```bash
curl "http://localhost:8000/v1/map/cells?bbox=-73.99,40.74,-73.97,40.75&factors=transit,grocery&weights=transit:2"
```

```json
{
  "precision": 6,
  "factors": ["grocery", "transit"],
  "weights": { "grocery": 1.5, "transit": 2.0 },
  "weightsVersion": "v1-handtuned",
  "count": 4,
  "truncated": false,
  "geohashes": ["dr5ru3", "dr5ru6", "dr5ru9", "dr5rud"],
  "scores": [99.8, 99.3, 98.7, 99.4]
}
```

A viewport spanning the whole covered area holds about 64,000 cells at `precision=6` (so `truncated` will be true even at the maximum `limit`) and about 2,100 at `precision=5`.

Errors: `400 invalid_request` for a missing, malformed or inverted `bbox` (min must be less than max; latitudes within +-90, longitudes within +-180), an unknown factor (including in `weights`), an empty `factors`, a weight that is not a number, is 0 or negative, is NaN/infinite or is above 1,000,000, a repeated weight, `precision` other than 5 or 6, or `limit` out of range.

```json
{ "code": "invalid_request", "message": "unknown factor 'foo'; valid factors: grocery, gym, cafe, gasStation, convenienceStore, transit, school, road, emergencyCorridor, airport, trailPopularity" }
```

---

## `GET /map/top`

*Available after the next deploy.*

"Where should I look?" Ranks cells by the same composite as `/map/cells`, then walks down the list keeping each cell that is at least `minSeparationKm` from every cell already kept, so you get distinct neighbourhoods rather than ten adjacent blocks. Because scores are relative within each metro area, the winners are the best spots in their metro area for the factors you chose; narrowing `factors` to one or two shows where each is at its maximum (with `factors=transit` the top score is 100).

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `bbox` | string | no | Restrict to a viewport (`minLon,minLat,maxLon,maxLat`). Omit for the whole covered area. |
| `factors` | string | no | As for `/map/cells` |
| `weights` | string | no | As for `/map/cells` |
| `limit` | integer | no | 1 to 50, default 10 |
| `minSeparationKm` | number | no | 0 to 50, default 3 |

You get up to `limit` results, fewer if the area (or the separation) leaves no more candidates. Each result has `geohash`, `latitude` and `longitude` (the cell's grid point), `score` (rounded to one decimal), `metroArea`, and the full `subScores` object for the cell (all eleven factors, whatever you selected for the ranking).

```bash
curl "http://localhost:8000/v1/map/top?factors=transit,cafe&bbox=-74.05,40.68,-73.85,40.82&limit=2&minSeparationKm=3"
```

```json
{
  "factors": ["cafe", "transit"],
  "weights": { "cafe": 1.0, "transit": 1.5 },
  "weightsVersion": "v1-handtuned",
  "results": [
    {
      "geohash": "dr5ru0",
      "latitude": 40.7384,
      "longitude": -73.996,
      "score": 99.9,
      "metroArea": "nyc",
      "subScores": {
        "grocery": 97.870276450581, "gym": 98.0771040262513, "cafe": 99.9721646287845,
        "gasStation": 4.88646449790451, "convenienceStore": 2.07266078607431,
        "transit": 99.9076271852118, "school": 81.9847697886939, "road": 91.4340718290933,
        "emergencyCorridor": 95.2017961535992, "airport": 57.8641370869033,
        "trailPopularity": 79.4262789427787
      }
    },
    {
      "geohash": "dr5reg",
      "latitude": 40.7114,
      "longitude": -74.007,
      "score": 99.9,
      "metroArea": "nyc",
      "subScores": { "...": "trimmed, same eleven keys as above" }
    }
  ]
}
```

Errors: the same `400 invalid_request` cases as `/map/cells` for `bbox`, `factors` and `weights`, plus `limit` outside 1-50 or `minSeparationKm` outside 0-50.

---

## Code examples

### JavaScript

```js
const API = "https://api.benrispace.com/v1";

async function api(path, params = {}) {
  const url = new URL(API + path);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url);
  const body = await res.json();
  if (!res.ok) throw new Error(`${body.code}: ${body.message}`);
  return body;
}

// Score a coordinate (works today). In a browser this only works from benrispace.com.
const score = await api("/score", { lat: 40.7484, lon: -73.9857 });
console.log(score.compositeScore, score.subScores.transit);

// Autocomplete, then score the chosen suggestion (after the next deploy).
const { suggestions } = await api("/suggest", { q: "350 5th ave" });
const pick = suggestions[0];
const picked = await api("/score", { lat: pick.latitude, lon: pick.longitude });

// Best areas for transit and cafes, weighting transit double (after the next deploy).
const top = await api("/map/top", { factors: "transit,cafe", weights: "transit:2", limit: 5 });
for (const r of top.results) console.log(r.geohash, r.score, r.metroArea);
```

### Python

```python
import httpx

API = "https://api.benrispace.com/v1"

with httpx.Client(base_url=API, timeout=20) as client:
    # Works today.
    score = client.get("/score", params={"lat": 40.7484, "lon": -73.9857}).json()
    print(score["compositeScore"], score["subScores"]["transit"])

    # After the next deploy.
    cells = client.get(
        "/map/cells",
        params={
            "bbox": "-73.99,40.74,-73.97,40.75",
            "factors": "transit,grocery",
            "weights": "transit:2",
        },
    ).json()
    for geohash, value in zip(cells["geohashes"], cells["scores"]):
        print(geohash, value)

    resp = client.get("/map/top", params={"factors": "bogus"})
    if resp.status_code != 200:
        error = resp.json()  # {"code": "invalid_request", "message": "..."}
        print(error["code"], error["message"])
```

The `/score` calls in these snippets (and the geohash decoder above) were run against the production API when this guide was written; the `/suggest` and `/map/*` calls were run against the same code locally.
