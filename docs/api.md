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
| `POST /triangulate` | Best locations that satisfy several commute anchors | live (straight-line circles until Phase 2 adds real routing, see below) |
| `GET /suggest` | Address autocomplete | live |
| `GET /reverse` | Readable address for a map point | live |
| `GET /map/cells` | Composite score per map cell for a chosen set of factors | live |
| `GET /map/top` | Best, well-separated areas for a chosen set of factors | live |

**Which examples are real.** The `/score`, `/area`, `/score/{id}/explanation`, `/reverse` and `/map/top` examples are real production responses captured after the v2 cutover (2026-10-03), with numbers rounded for readability (and the `/area` polygon shortened). The `/triangulate`, `/suggest` and `/map/cells` examples were captured earlier and still have the right shape; their numbers predate the v2 data and are for shape only.

**v2 status.** The v2 cutover is complete. Production serves `weightsVersion: "v2-handtuned"` (64,320 score rows, fourteen factors), including restaurant, bar, premium retail, the facility-based noise corridor and click-to-polygon `/area`. `subScores.school` is `null` wherever no district rating exists (shown as "No data" on the website); any other factor can also be `null` if its data is missing for a cell.

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
- The **composite** (`compositeScore`) is a weighted average of the fourteen sub-scores. Default weights (version `v2-handtuned`, which production serves; the retired `v1-handtuned` had eleven factors, without restaurant, bar and premiumRetail): grocery 1.5, gym 1.0, cafe 1.0, restaurant 1.0, bar 0.5, premiumRetail 0.75, gasStation 1.0, convenienceStore 0.75, transit 1.5, school 1.5, road 1.0, emergencyCorridor 0.75, airport 0.75, trailPopularity 1.25. `/map/cells` and `/map/top` let you choose your own factors and weights.
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

Brand matching for `premiumRetail` uses the OpenStreetMap `brand:wikidata` tag (Whole Foods Q1809448, Starbucks Q37158 and Starbucks Reserve Q71150001, Target Q1046951), with a name fallback. `school` is 20% proximity and 80% district rating, and `null` where no rating exists (see [data-sources.md](data-sources.md)). The API serves only rows matching its configured weights version (`SCORING_WEIGHTS_VERSION`, set to `v2-handtuned` in production), so rows from an older version are never mixed in.

**Known limitation (v3 candidate).** Each factor is min-max normalized within its metro area, so a few extreme outlier distances stretch the scale and skew everyone else's scores. A visible symptom: remote cells with very little around them can still score high on `restaurant` and `bar`. A more robust normalization (percentile or log-scaled distances) is a scoring v3 candidate; see `PHASES.md`.

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
curl "https://api.benrispace.com/v1/score?lat=40.7546&lon=-73.985"
```

```json
{
  "geoEntityId": "3fd189bb-d488-427d-87ae-6753f0304789",
  "address": "40.75460,-73.98500",
  "latitude": 40.7546,
  "longitude": -73.985,
  "compositeScore": 81.7,
  "subScores": {
    "grocery": 99.7,
    "gym": 99.8,
    "cafe": 99.8,
    "restaurant": 99.5,
    "bar": 99.0,
    "premiumRetail": 100.0,
    "gasStation": 8.5,
    "convenienceStore": 2.1,
    "transit": 99.9,
    "school": null,
    "road": 89.0,
    "emergencyCorridor": 96.5,
    "airport": 63.4,
    "trailPopularity": 79.8
  },
  "weightsVersion": "v2-handtuned",
  "computedAt": "2026-10-03T01:16:27Z",
  "school": {
    "proximity": 96.2,
    "ratingAvailable": false,
    "districtName": "New York City Department Of Education",
    "source": null
  }
}
```

### Units: feet and miles

Everything user-facing is in feet and miles: distances in text, `nearestMi`, `minSeparationMi`, the cell sizes above. Internally the data and the scoring stay metric (the `*_500m` / `*_nearest_m` columns and radii), so a "within 500 m" count is described to users as about 0.3 mi. Distances in prose follow one rule: under 0.1 mi they are feet rounded to the nearest 50 (`450 ft`), otherwise miles to one decimal (`0.4 mi`).

### `school`

Alongside `subScores.school` (which is `null` when no school rating exists for the location, as in the example above) the response carries a `school` object, or `null` for older rows scored before school data existed. In the example, the location has a school proximity of 96 but no district rating (`ratingAvailable: false`), so `subScores.school` is `null`.

`proximity` is 0-100 and counts schools nearby regardless of rating, so a client can show "proximity 96, rating unavailable". `ratingAvailable` is true when `subScores.school` is non-null. `districtName` and `source` come from the stored school-district data and may be `null`.

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
curl "https://api.benrispace.com/v1/area?lat=40.672&lon=-73.978"
```

Real response (Park Slope, Brooklyn); the polygon is shortened here to a few vertices, the real one has about 100:

```json
{
  "geoEntityId": "2cedabc0-6869-45a7-8799-760614d657d1",
  "address": "Area bounded by Prospect Expy, 4th Ave, Flatbush Ave and Union St",
  "latitude": 40.672,
  "longitude": -73.978,
  "compositeScore": 76.8,
  "subScores": {
    "grocery": 97.2, "gym": 98.0, "cafe": 98.4, "restaurant": 97.3, "bar": 97.2,
    "premiumRetail": 43.4, "gasStation": 6.8, "convenienceStore": 1.9, "transit": 99.2,
    "school": null, "road": 93.0, "emergencyCorridor": 98.0, "airport": 42.4,
    "trailPopularity": 82.2
  },
  "weightsVersion": "v2-handtuned",
  "computedAt": "2026-10-03T01:16:27Z",
  "school": {
    "proximity": 92.3,
    "ratingAvailable": false,
    "districtName": "New York City Department Of Education",
    "source": null
  },
  "areaId": 5432,
  "area": {
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[-73.97204, 40.65137], [-73.97545, 40.64976], [-73.99274, 40.66546], [-73.97295, 40.67349], [-73.96238, 40.6631], [-73.97204, 40.65137]]]
    },
    "areaSqMi": 1.78,
    "boundedBy": ["Prospect Expy", "4th Ave", "Flatbush Ave", "Union St"],
    "cellCount": 16
  },
  "explanation": "This area's strongest factor is transit access (99/100). Its weakest factor is distance from convenience stores (2/100). Other factors: cafe access 98/100, gym access 98/100, distance from the noise corridor 98/100, restaurant access 97/100, bar and pub access 97/100, grocery access 97/100, road and traffic conditions 93/100, access to popular running and walking trails 82/100, access to premium retail (Whole Foods, Starbucks, Target) 43/100, airport drive time 42/100, distance from gas stations 7/100. Nearest feature from this spot: transit access 500 ft, distance from convenience stores 500 ft."
}
```

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | `lat`/`lon` missing, not numbers, or out of range |
| 404 | `area_not_found` | No area contains or is within 40 m of the point, the area is larger than 10 square miles, no cell has a score, or areas have not been built yet. Fall back to `GET /score?lat=&lon=` |
| 422 | `out_of_coverage` | The point is outside the covered metro area |

## `GET /score/{geoEntityId}/explanation`

A short plain-language explanation of one score: the strongest factor, the weakest, the rest, and (when known) the distance to the nearest feature for the strongest and weakest. Live today and rule-based (`api/explain.py`, no LLM involved). The LLM-written version is planned for Phase 3 and would not change the response shape.

| Parameter | In | Type | Description |
| --- | --- | --- | --- |
| `geoEntityId` | path | UUID | The `geoEntityId` from a `/score` response |

```bash
curl "https://api.benrispace.com/v1/score/2cedabc0-6869-45a7-8799-760614d657d1/explanation"
```

```json
{
  "geoEntityId": "2cedabc0-6869-45a7-8799-760614d657d1",
  "explanation": "This location's strongest factor is transit access (99/100). Its weakest factor is distance from convenience stores (2/100). Other factors: cafe access 98/100, gym access 98/100, distance from the noise corridor 98/100, restaurant access 97/100, bar and pub access 97/100, grocery access 97/100, road and traffic conditions 93/100, access to popular running and walking trails 82/100, access to premium retail (Whole Foods, Starbucks, Target) 43/100, airport drive time 42/100, distance from gas stations 7/100. Nearest feature from this spot: transit access 500 ft, distance from convenience stores 500 ft.",
  "computedAt": "2026-10-03T01:16:27Z"
}
```

(The text above is the explanation captured from production for this cell; the response also carries `nearestMi`, described next.)

Distances in the text are in feet and miles. The response also carries `nearestMi`, the distance in miles to the nearest feature per factor (a number, or `null` when unknown), for the factors that have one: `grocery`, `gym`, `cafe`, `restaurant`, `bar`, `gasStation`, `convenienceStore`, `transit`, `school`, `trailPopularity`, `premiumRetail` (the nearest of Whole Foods, Starbucks and Target) and `emergencyCorridor` (the nearest emergency facility). `road` and `airport` are not included. Where a distance is unknown the value is `null`, and the explanation omits its "Nearest feature" sentence. Shape:

```json
{ "nearestMi": { "grocery": 0.2, "gym": null, "premiumRetail": 0.8 } }
```

Errors: `400 invalid_request` if the id is not a UUID, `404 not_found` if no score exists for it.

---

## `POST /triangulate`

Given up to four anchors (workplace, gym, family, ...) with a maximum travel time each, return the best-scoring locations reachable from all of them (`intersect`) or any of them (`union`), ranked by composite score. Candidate cells are prefiltered with a bounding box derived from the anchor circles.

**This endpoint is live but uses placeholder geometry.** There is no routing engine yet (Valhalla arrives with Phase 2), so each anchor's reachable area is a straight-line circle, with radius = `maxTravelMinutes` x an assumed average speed for the mode (drive 25 mph, transit 15.5 mph, walk 3 mph). Ignoring rivers, bridges, highways and real transit lines, it can be off by a lot, particularly across water. Real isochrones will replace it; the request and response shapes are not expected to change.

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
curl "https://api.benrispace.com/v1/reverse?lat=40.758&lon=-73.9855"
```

```json
{ "label": "7th Avenue, New York, NY", "latitude": 40.758, "longitude": -73.9855 }
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
  "weightsVersion": "v2-handtuned",
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
curl "https://api.benrispace.com/v1/map/top?limit=2"
```

With no `factors` or `weights`, all fourteen factors and their default weights are used (real response, rounded; the sub-scores are shown on one line each for space):

```json
{
  "factors": ["grocery", "gym", "cafe", "restaurant", "bar", "premiumRetail", "gasStation", "convenienceStore", "transit", "school", "road", "emergencyCorridor", "airport", "trailPopularity"],
  "weights": { "grocery": 1.5, "gym": 1.0, "cafe": 1.0, "restaurant": 1.0, "bar": 0.5, "premiumRetail": 0.75, "gasStation": 1.0, "convenienceStore": 0.75, "transit": 1.5, "school": 1.5, "road": 1.0, "emergencyCorridor": 0.75, "airport": 0.75, "trailPopularity": 1.25 },
  "weightsVersion": "v2-handtuned",
  "results": [
    {
      "geohash": "dr5xsj",
      "latitude": 40.7228,
      "longitude": -73.651,
      "score": 83.0,
      "metroArea": "long_island",
      "subScores": {
        "grocery": 97.6, "gym": 96.7, "cafe": 99.9, "restaurant": 96.9, "bar": 96.5,
        "premiumRetail": 62.6, "gasStation": 3.4, "convenienceStore": 3.1, "transit": 98.4,
        "school": 89.9, "road": 90.9, "emergencyCorridor": 99.7, "airport": 95.2,
        "trailPopularity": 98.5
      }
    },
    {
      "geohash": "dr73hc",
      "latitude": 40.9678,
      "longitude": -73.968,
      "score": 83.0,
      "metroArea": "northern_nj",
      "subScores": {
        "grocery": 98.1, "gym": 94.9, "cafe": 96.4, "restaurant": 96.0, "bar": 87.0,
        "premiumRetail": 56.5, "gasStation": 17.5, "convenienceStore": 10.1, "transit": 96.2,
        "school": 95.0, "road": 97.9, "emergencyCorridor": 100.0, "airport": 88.2,
        "trailPopularity": 89.4
      }
    }
  ]
}
```

Note the second result: a spot at 40.97 N is far from the dense core yet scores 87 on `bar` and 96 on `restaurant`. That is the min-max normalization weakness described under "What a score means" (a v3 candidate), not a real nightlife hub.

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

The `/score` calls in these snippets (and the geohash decoder above) were run against the production API when this guide was written; the `/suggest` and `/map/*` calls were run against the same code locally before the v2 deploy. Production now serves `v2-handtuned`, so `/score` responses carry fourteen sub-scores.
