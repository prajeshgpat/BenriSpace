# BenriSpace API

BenriSpace scores how convenient a location is to live at, 0 to 100, for the New York metro area (NYC, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County, CT).

- **Base URL:** `https://api.benrispace.com/v1`
- **Interactive docs (Swagger UI):** <https://api.benrispace.com/docs>
- **Machine-readable spec:** <https://api.benrispace.com/openapi.json> (the source contract lives in [`contracts/openapi.yaml`](../contracts/openapi.yaml))

| Endpoint | Purpose | Status |
| --- | --- | --- |
| `GET /score` | Score for one address or coordinate | live |
| `GET /score/{geoEntityId}/explanation` | Plain-language explanation of a score | live |
| `GET /area` | Score for the road-bounded area under a point | live |
| `POST /triangulate` | Best locations that satisfy several commute anchors | live (placeholder geometry, see below) |
| `GET /suggest` | Address autocomplete | live |
| `GET /reverse` | Readable address for a map point | live |
| `GET /map/cells` | Composite score per map cell for a chosen set of factors | live |
| `GET /map/top` | Best, well-separated areas for a chosen set of factors | live |

**Which examples are real.** Examples for `/score`, `/score/{id}/explanation`, `/triangulate`, `/suggest`, `/reverse`, `/map/cells` and `/map/top` are real responses captured when this guide was written. They predate the v2 data cutover, so they show `weightsVersion: "v1-handtuned"` and only the original eleven sub-scores. Examples marked "illustrative" (`/area` and the `school` and `nearestMi` shapes) show structure only; their values are made up.

**v2 status.** The v2 code (fourteen factors, `/area`, `/reverse`, miles) is deployed. The v2 data ingestion and the switch of the API to `v2-handtuned` scores are still in progress. Until the cutover the API serves `v1-handtuned` scores, so restaurant, bar, premium retail and the facility-based noise corridor are absent or `null` ("No data" on the website), and school ratings are missing where not yet loaded.

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
- **Caching:** `/area`, `/suggest`, `/reverse`, `/map/cells` and `/map/top` send `Cache-Control: public, max-age=300`. Scores only change when the weekly data refresh runs.
- **Rate limiting:** the API Gateway currently allows a steady 10 requests per second with bursts of 20, across all callers. Beyond that you get `429 Too Many Requests` (from API Gateway, not the application, so the body is not in the error shape above). Per-user quotas arrive with API keys.

## What a score means

- Scores run from **0 to 100, and higher is always better**. Factors where less is better (gas stations nearby, traffic, the noise corridor, airport drive time) are already inverted, so a high `gasStation` score means "far from gas stations".
- Scores are **relative within a metro area**, not absolute. Each factor is min-max normalized across all cells in the same metro area (for example `nyc` or `northern_nj`), so 100 means "best in its metro area for this factor" and 0 means "worst". A suburban cell is compared with other suburban cells in its own area, not with Manhattan.
- **No location scores 100 on everything.** Factors pull in opposite directions: the spots with the best transit, cafes and groceries are dense, and dense places have more gas stations, traffic and siren noise. In the example below, 350 5th Avenue scores 100 on transit but 10 on distance from gas stations. A composite near 80 is exceptional.
- Scores describe an **area**, not a single building. The underlying grid cells are about 0.6 by 0.4 miles, and the small road-bounded areas returned by `/area` are averages of the cells they overlap, so neighbouring small areas often share similar scores.
- The **composite** (`compositeScore`) is a weighted average of the fourteen sub-scores. Default weights (version `v2-handtuned`; the older `v1-handtuned` has eleven factors, without restaurant, bar and premiumRetail): grocery 1.5, gym 1.0, cafe 1.0, restaurant 1.0, bar 0.5, premiumRetail 0.75, gasStation 1.0, convenienceStore 0.75, transit 1.5, school 1.5, road 1.0, emergencyCorridor 0.75, airport 0.75, trailPopularity 1.25. `/map/cells` and `/map/top` let you choose your own factors and weights.
- `weightsVersion` tells you which set of stored scores you are looking at.

### The fourteen factors

| Key | Meaning of a high score |
| --- | --- |
| `grocery` | Grocery stores close by |
| `gym` | Gyms close by |
| `cafe` | Cafes close by |
| `restaurant` | Restaurants close by (`amenity=restaurant` only) |
| `bar` | Bars, pubs and beer gardens close by |
| `premiumRetail` | Close to Whole Foods, Starbucks and Target (underlying metric) |
| `gasStation` | Far from gas stations |
| `convenienceStore` | Far from convenience stores |
| `transit` | Close to frequent transit stops |
| `school` | Schools close by and well rated |
| `road` | Light traffic and congestion nearby |
| `emergencyCorridor` | Far from the noise corridor (displayed as "Noise corridor") |
| `airport` | Short drive to a major airport |
| `trailPopularity` | Mapped running trails close by (underlying metric) |

Brand matching for `premiumRetail` uses the OpenStreetMap `brand:wikidata` tag (Whole Foods Q1809448, Starbucks Q37158 and Starbucks Reserve Q71150001, Target Q1046951), with a name fallback. `school` is 20% proximity and 80% district rating, and `null` where no rating exists (see [data-sources.md](data-sources.md)). The API serves only rows matching its configured weights version (`SCORING_WEIGHTS_VERSION`, `v1-handtuned` until the v2 cutover), so rows from an older version lack the newer factors.

**Noise corridor.** The `emergencyCorridor` factor is displayed as "Noise corridor": main roads near fire stations, hospitals and police stations, where sirens and through-traffic noise are most likely. It is a rough proxy (default weight 0.75). The API key `emergencyCorridor` and the database columns keep their names.

**Underlying metrics.** `premiumRetail` and `trailPopularity` (running route popularity, built from mapped running trails in OpenStreetMap; Strava segment popularity is an optional enrichment that is not configured today) are underlying metrics. They count toward the overall score, but the website offers no toggle for them. The API does not treat them specially: omit `factors` and all fourteen factors are used, underlying ones included; send an explicit `factors` list and exactly those factors are used.

## Geohash cells

The metro area is divided into a grid of **geohash6** cells, roughly 0.6 by 0.4 miles. Every score belongs to one cell. `/map/cells` identifies cells by their geohash string (for example `dr5ru0`); with `precision=5` the cells are about 2.3 by 3 miles (`dr5ru`), and each one is the average of the finer cells inside it.

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

The point is snapped to its geohash6 cell; if that exact cell is not in the grid, the nearest covered cell within about 2 miles is used.

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

### Units: feet and miles

Everything user-facing is in feet and miles: distances in text, `nearestMi`, `minSeparationMi`, the cell sizes above. Internally the data and the scoring stay metric (the `*_500m` / `*_nearest_m` columns and radii), so a "within 500 m" count is described to users as about 0.3 mi. Distances in prose follow one rule: under 0.1 mi they are feet rounded to the nearest 50 (`450 ft`), otherwise miles to one decimal (`0.4 mi`).

### `school`

Shape only (illustrative). Alongside `subScores.school` (which is `null` when no school rating exists for the location) the response carries a `school` object, or `null` for rows scored before school data was ingested:

```json
{ "school": { "proximity": 72.0, "ratingAvailable": false, "districtName": "Example UFSD", "source": "example-source" } }
```

`proximity` is 0-100 and counts schools nearby regardless of rating, so a client can show "proximity 72, rating unavailable". `ratingAvailable` is true when `subScores.school` is non-null. `districtName` and `source` come from the stored school-district data and may be `null`. The values above only illustrate the shape.

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

## `GET /area`

Score for the whole **road-bounded area** under a point: the block of land enclosed by secondary-and-larger roads (secondary, primary, trunk, motorway) and the shoreline. The website calls this when you click the map and draws the polygon; on a 404 it falls back to the single grid cell. Sub-scores are the area-weighted average of the latest scores of the geohash6 cells the area overlaps, skipping cells that lack a given factor. `compositeScore` is the area-weighted average of those cells' composite scores (what the map shows), so it can differ slightly from recomputing a composite from the averaged sub-scores. Results are cached for 5 minutes.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `lat` | number | yes | Latitude, inside the covered area |
| `lon` | number | yes | Longitude, inside the covered area |

The point picks the smallest area whose polygon contains it; a point within 40 m of an area's edge (a click on the road itself) snaps to that area. `geoEntityId`, `school` district and the nearest-feature distances in `explanation` come from the grid cell under the point; `address` is "Area bounded by ..." with up to four road names. `area.geometry` is a GeoJSON Polygon or MultiPolygon in `[lon, lat]`.

```bash
curl "http://localhost:8000/v1/area?lat=40.7484&lon=-73.9857"
```

Shape only (illustrative). The values below are made up, not real data, and `subScores` is shortened:

```json
{
  "geoEntityId": "00000000-0000-0000-0000-000000000000",
  "address": "Area bounded by Road A, Road B, Road C and Road D",
  "latitude": 40.7484,
  "longitude": -73.9857,
  "compositeScore": 70.0,
  "subScores": { "grocery": 70.0, "gym": 70.0, "...": 70.0 },
  "weightsVersion": "v1-handtuned",
  "computedAt": "2026-01-01T00:00:00Z",
  "school": null,
  "areaId": 1,
  "area": {
    "geometry": { "type": "Polygon", "coordinates": [[[-73.99, 40.74], [-73.98, 40.74], [-73.98, 40.75], [-73.99, 40.74]]] },
    "areaSqMi": 0.5,
    "boundedBy": ["Road A", "Road B", "Road C", "Road D"],
    "cellCount": 3
  },
  "explanation": "This area's strongest factor is ... Nearest feature from this spot: ..."
}
```

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | `lat`/`lon` missing, not numbers, or out of range |
| 404 | `area_not_found` | No area contains or is within 40 m of the point, the area is larger than 10 square miles, no cell has a score, or areas have not been built yet. Fall back to `GET /score?lat=&lon=` |
| 422 | `out_of_coverage` | The point is outside the covered metro area |

## `GET /score/{geoEntityId}/explanation`

A short plain-language explanation of one score: the strongest factor, the weakest, the rest, and (when known) the distance to the nearest feature for the strongest and weakest. Currently generated from a template (RAG-written explanations are a later phase); an LLM-written explanation may replace it later without changing the shape.

| Parameter | In | Type | Description |
| --- | --- | --- | --- |
| `geoEntityId` | path | UUID | The `geoEntityId` from a `/score` response |

```bash
curl "https://api.benrispace.com/v1/score/21c5d4bd-e66e-423b-8f4c-8e569604f187/explanation"
```

```json
{
  "geoEntityId": "21c5d4bd-e66e-423b-8f4c-8e569604f187",
  "explanation": "This location's strongest factor is transit access (100/100). Its weakest factor is distance from convenience stores (2/100). Other factors: cafe access 99/100, grocery access 99/100, gym access 98/100, distance from the noise corridor 95/100, road and traffic conditions 85/100, access to popular running and walking trails 79/100, school quality and proximity 77/100, airport drive time 63/100, distance from gas stations 10/100.",
  "computedAt": "2026-09-30T15:02:10.262476Z"
}
```

Distances in the text are in feet and miles. The response also carries `nearestMi`, the distance in miles to the nearest feature per factor (a number, or `null` when unknown), for the factors that have one: `grocery`, `gym`, `cafe`, `restaurant`, `bar`, `gasStation`, `convenienceStore`, `transit`, `school`, `trailPopularity`, `premiumRetail` (the nearest of Whole Foods, Starbucks and Target) and `emergencyCorridor` (the nearest emergency facility). `road` and `airport` are not included. For locations scored before the newer data was ingested the values are `null`, and the explanation omits its "Nearest feature" sentence. Shape (illustrative):

```json
{ "nearestMi": { "grocery": 0.2, "gym": null, "premiumRetail": 0.8 } }
```

Errors: `400 invalid_request` if the id is not a UUID, `404 not_found` if no score exists for it.

---

## `POST /triangulate`

Given up to four anchors (workplace, gym, family, ...) with a maximum travel time each, return the best-scoring locations reachable from all of them (`intersect`) or any of them (`union`), ranked by composite score. Candidate cells are prefiltered with a bounding box derived from the anchor circles.

**This is a placeholder.** There is no routing engine yet, so each anchor's reachable area is a straight-line circle, with radius = `maxTravelMinutes` x an assumed average speed for the mode (drive 25 mph, transit 15.5 mph, walk 3 mph). Ignoring rivers, bridges, highways and real transit lines, it can be off by a lot, particularly across water. Real isochrones will replace it; the request and response shapes are not expected to change.

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

Address autocomplete for a search box. Returns up to `limit` places for what the user has typed so far, restricted to the covered area and biased toward the middle of the metro. Pass a suggestion's `latitude`/`longitude` straight to `GET /score?lat=&lon=`, which skips geocoding.

Suggestions come from [LocationIQ](https://locationiq.com) when the server has an API key (the primary provider), with [Photon](https://photon.komoot.io), a keyless geocoder built on OpenStreetMap data, as the fallback. Both are proxied so browsers never talk to them directly. Nominatim is not used for autocomplete because its usage policy forbids it. Results are cleaned up before you see them: labels are built as `house number + street, city, state` (NY, NJ, CT, PA abbreviated), point-of-interest names at an address are replaced by the address itself, and duplicate labels or points within 25 m of each other are merged. A query that starts with a digit lists addresses before streets and landmarks. The same query is cached on the server for 10 minutes.

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
| 503 | `suggest_unavailable` | Every provider timed out (3 s for LocationIQ, 8 s for Photon), returned an error, or sent something unreadable |

On a 503, fall back to plain-text search (`GET /score?address=...`) rather than showing an error. Error responses are not cached.

---

## `GET /reverse`

Turns a coordinate (for example a map click) into a short readable address. The label is `house number + street, locality, state` (NY, NJ, CT, PA abbreviated), the same style as `/suggest` (LocationIQ first, Photon as the fallback). With no house number it is the street; with no street it is the neighbourhood name; if nothing usable is known, `label` is `null` (still HTTP 200). The point is echoed back as sent. Results are cached on the server for 10 minutes, by coordinates rounded to 4 decimals (about 11 m).

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `lat` | number | yes | Latitude, inside the covered area |
| `lon` | number | yes | Longitude, inside the covered area |

```bash
curl "http://localhost:8000/v1/reverse?lat=40.7314&lon=-74.0635"
```

```json
{ "label": "9 Journal Square Concourse, Jersey City, NJ", "latitude": 40.7314, "longitude": -74.0635 }
```

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | `lat`/`lon` missing, not numbers, or outside -90..90 / -180..180 |
| 422 | `out_of_coverage` | The point is outside the covered metro area |
| 503 | `reverse_unavailable` | Every provider timed out, errored or sent something unreadable |

On a 503, show the coordinates (or nothing) rather than an error. Error responses are not cached.

---

## `GET /map/cells`

Composite score for every grid cell inside a map viewport, calculated for the factors and weights you choose. It is a weighted average of the stored sub-scores (not a recalculation from raw data), so it is cheap to call whenever the user toggles a filter.

For each cell, the composite uses only the selected factors that are not `null` for that cell, so the denominator counts only the weights of factors that have data; cells where every selected factor is `null` are left out.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `bbox` | string | yes | Viewport as `minLon,minLat,maxLon,maxLat`. Cells whose grid point lies inside are returned. |
| `precision` | integer | no | `6` (default, about 0.6 x 0.4 mile cells) or `5` (about 2.3 x 3 miles; the mean of the finer cells). Use 5 when zoomed out. |
| `factors` | string | no | Comma-separated factor keys to include, for example `transit,cafe`. Omit for all fourteen (including the underlying `premiumRetail` and `trailPopularity`); an explicit list means exactly those factors. Must not be empty if present. |
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
{ "code": "invalid_request", "message": "unknown factor 'foo'; valid factors: grocery, gym, cafe, restaurant, bar, premiumRetail, gasStation, convenienceStore, transit, school, road, emergencyCorridor, airport, trailPopularity" }
```

---

## `GET /map/top`

"Where should I look?" Ranks cells by the same composite as `/map/cells`, then walks down the list keeping each cell that is at least `minSeparationMi` from every cell already kept, so you get distinct neighbourhoods rather than ten adjacent blocks. Because scores are relative within each metro area, the winners are the best spots in their metro area for the factors you chose; narrowing `factors` to one or two shows where each is at its maximum (with `factors=transit` the top score is 100).

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `bbox` | string | no | Restrict to a viewport (`minLon,minLat,maxLon,maxLat`). Omit for the whole covered area. |
| `factors` | string | no | As for `/map/cells` |
| `weights` | string | no | As for `/map/cells` |
| `limit` | integer | no | 1 to 50, default 10 |
| `minSeparationMi` | number | no | Minimum distance between returned areas, in miles. 0 to 31; default about 1.9 (equal to the old 3 km default). |
| `minSeparationKm` | number | no | **Deprecated**, still works. Kilometres, 0 to 50, default 3. Sending it together with `minSeparationMi` is a `400 invalid_request`. |

You get up to `limit` results, fewer if the area (or the separation) leaves no more candidates. Each result has `geohash`, `latitude` and `longitude` (the cell's grid point), `score` (rounded to one decimal), `metroArea`, and the full `subScores` object for the cell (all fourteen factors, whatever you selected for the ranking).

```bash
curl "http://localhost:8000/v1/map/top?factors=transit,cafe&bbox=-74.05,40.68,-73.85,40.82&limit=2&minSeparationMi=2"
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
      "subScores": { "...": "trimmed, same fourteen keys as above" }
    }
  ]
}
```

Errors: the same `400 invalid_request` cases as `/map/cells` for `bbox`, `factors` and `weights`, plus `limit` outside 1-50, `minSeparationMi` outside 0-31 (or `minSeparationKm` outside 0-50), or both separation parameters at once. The response has no separation field; the spacing is applied, not echoed.

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

// Score a coordinate In a browser this only works from benrispace.com.
const score = await api("/score", { lat: 40.7484, lon: -73.9857 });
console.log(score.compositeScore, score.subScores.transit);

// Autocomplete, then score the chosen suggestion.
const { suggestions } = await api("/suggest", { q: "350 5th ave" });
const pick = suggestions[0];
const picked = await api("/score", { lat: pick.latitude, lon: pick.longitude });

// Best areas for transit and cafes, weighting transit double.
const top = await api("/map/top", { factors: "transit,cafe", weights: "transit:2", limit: 5 });
for (const r of top.results) console.log(r.geohash, r.score, r.metroArea);
```

### Python

```python
import httpx

API = "https://api.benrispace.com/v1"

with httpx.Client(base_url=API, timeout=20) as client:
    score = client.get("/score", params={"lat": 40.7484, "lon": -73.9857}).json()
    print(score["compositeScore"], score["subScores"]["transit"])

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

The `/score` calls in these snippets (and the geohash decoder above) were run against the production API when this guide was written; the `/suggest` and `/map/*` calls were run against the same code locally before the v2 deploy. After the data cutover, responses show `v2-handtuned` and fourteen sub-scores.
