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
| `GET /area/explanation` | AI-written (or rule-based) explanation for the area under a point | live |
| `POST /triangulate` | Best locations that satisfy several commute anchors | live (straight-line circles until Phase 2 adds real routing, see below) |
| `POST /optimize` | Neighborhoods that minimise weekly travel to several destinations (work, a store brand, a gym) | built, not yet deployed |
| `POST /chat` | Ask Benri: a tool-using chat assistant grounded in our own data (15 messages a day per visitor) | built, needs migration 0010 for the daily limit |
| `POST /chat/stream` | The same chat as server-sent events (progress, then the reply) | built, not deployed |
| `GET /suggest` | Address autocomplete | live |
| `GET /reverse` | Readable address for a map point | live |
| `GET /improve` | Deterministic suggestions for raising the weakest factors | live |
| `GET /similar` | Well-separated areas with a similar factor profile (pgvector) | built, needs migration 0007 |
| `GET /map/cells` | Composite score per map cell for a chosen set of factors | live |
| `GET /map/top` | Best, well-separated areas for a chosen set of factors | live |

**Which examples are real.** The `/score`, `/area`, `/score/{id}/explanation`, `/reverse` and `/map/top` examples are real production responses captured after the v2 cutover (2026-10-03), with numbers rounded for readability (and the `/area` polygon shortened). The `/triangulate`, `/suggest` and `/map/cells` examples were captured earlier and still have the right shape; their numbers predate the v2 data and are for shape only.

**v2 status.** The v2 cutover is complete. Production serves `weightsVersion: "v2-handtuned"` (64,320 score rows, fourteen stored scores), including restaurant, bar, premium retail, the facility-based noise corridor and click-to-polygon `/area`. `subScores.school` is `null` wherever no district rating exists (shown as "No data" on the website); any other factor can also be `null` if its data is missing for a cell.

**v2.1 key names.** The API now answers with the thirteen v2.1 factors (`shopping`, `gasConvenience`, `traffic`, `recreation` replace `premiumRetail`, `gasStation`/`convenienceStore`, `road`, `trailPopularity`). The examples below show the production `v2-handtuned` rows read through those keys: `gasConvenience` is `null` on v2 rows (they scored gas stations and convenience stores as two negative factors), `shopping` comes from the old premium-retail score, `recreation` from the old trail score and `traffic` from the old road score. Rows scored as `v2.1-handtuned` fill all thirteen. The old keys are still accepted wherever you send `factors` or `weights` (see "The thirteen factors").

## Conventions

- **Authentication:** none today. Phase 4 will add API keys and usage tiers (an `Authorization: Bearer ...` or `X-API-Key` header).
- **JSON, camelCase:** every field name is camelCase (`compositeScore`, `geoEntityId`, `gasConvenience`).
- **Errors** always have the same shape, with an HTTP status that matches:

  ```json
  { "code": "invalid_request", "message": "bbox is empty or inverted: need minLon < maxLon and minLat < maxLat" }
  ```

  `code` is stable and meant for programs; `message` is for humans and may change.
- **`null` means "not measured", never 0.** A sub-score can be `null` when the underlying data does not exist for that spot yet. Treat it as unknown. Composites ignore `null` factors rather than counting them as zero.
- **CORS:** browsers may call the API only from `https://benrispace.com`, `https://www.benrispace.com` and `http://localhost:3000`. From any other origin the browser will block the response. Server-side clients (curl, Python, Node) are not affected by CORS.
- **Caching:** `/area`, `/area/explanation`, `/suggest`, `/reverse`, `/places`, `/improve`, `/similar`, `/map/cells` and `/map/top` send `Cache-Control: public, max-age=300`. Scores only change when the weekly data refresh runs.
- **Rate limiting:** the API Gateway currently allows a steady 10 requests per second with bursts of 20, across all callers. Beyond that you get `429 Too Many Requests` (from API Gateway, not the application, so the body is not in the error shape above). Per-user quotas arrive with API keys.

## What a score means

- Scores run from **0 to 100, and higher is always better**. Factors where less is better (traffic, the noise corridor, airport drive time) are already inverted, so a high `traffic` score means "light traffic nearby" and a high `emergencyCorridor` score means "far from the noise corridor".
- Scores are **relative within a metro area**, not absolute. Each factor is min-max normalized across all cells in the same metro area (for example `nyc` or `northern_nj`), so 100 means "best in its metro area for this factor" and 0 means "worst". A suburban cell is compared with other suburban cells in its own area, not with Manhattan.
- **No location scores 100 on everything.** Factors pull in opposite directions: the spots with the best transit, cafes and groceries are dense, and dense places have more traffic and siren noise. In the example below, 350 5th Avenue scores 100 on transit but a low score on distance from the noise corridor. A composite near 80 is exceptional.
- Scores describe an **area**, not a single building. The underlying grid cells are about 0.6 by 0.4 miles, and the small road-bounded areas returned by `/area` are averages of the cells they overlap, so neighbouring small areas often share similar scores.
- The **composite** (`compositeScore`) is a weighted average of the sub-scores, normalized by the weight of the factors that have a score (a `null` factor is left out, never counted as 0). The v2.1 default weights (version `v2.1-handtuned`, from docs/SCORING.md) are: grocery 14, transit 14, emergencyCorridor 12, restaurant 10, school 10, gym 9, cafe 8, gasConvenience 6, bar 5, airport 5, recreation 5, shopping 4, traffic 4. Production still serves `v2-handtuned` until the cutover; its stored composites use the older weights (grocery 1.5, gym 1.0, cafe 1.0, restaurant 1.0, bar 0.5, premium retail 0.75, gas station 1.0, convenience store 0.75, transit 1.5, school 1.5, road 1.0, emergencyCorridor 0.75, airport 0.75, trail popularity 1.25). `/map/cells` and `/map/top` let you choose your own factors and weights, always starting from the v2.1 weights.
- `weightsVersion` tells you which set of stored scores you are looking at.

### The thirteen factors

Every factor is a toggle on the website; none are hidden.

| Key | Website pill | Meaning of a high score |
| --- | --- | --- |
| `grocery` | Groceries | Grocery stores close by |
| `gym` | Gym | Gyms close by |
| `cafe` | Cafes | Cafes close by |
| `restaurant` | Restaurants | Restaurants close by (`amenity=restaurant` only) |
| `bar` | Bars | Bars, pubs and beer gardens close by |
| `shopping` | Shopping | General retail close by and varied (department stores, malls, clothing, home goods, pharmacies), with a small bonus for Whole Foods, Starbucks and Target |
| `gasConvenience` | Gas & Convenience | Gas stations and convenience stores close by (one positive factor; `null` on `v2-handtuned` rows) |
| `transit` | Public transit | Close to frequent transit stops |
| `school` | Schools | Schools close by and well rated |
| `traffic` | Traffic | Light traffic and congestion nearby |
| `emergencyCorridor` | Noise Corridor | Far from main roads near fire, police and hospital sites, and not right next to a gas station or convenience store |
| `airport` | Airport | Short drive to a major airport |
| `recreation` | Recreation | Parks, playgrounds and nature areas close and large, plus mapped running trails |

**Legacy keys.** `premiumRetail` is accepted as `shopping`, `trailPopularity` as `recreation`, `road` as `traffic`, and `gasStation` and `convenienceStore` both as `gasConvenience`, in every `factors` and `weights` parameter (the duplicates collapse; sending two aliases of one factor in `weights` is an error). Responses only use the new keys. `/places` still accepts `gasStation`, `convenienceStore` and `premiumRetail` with their exact old meaning.

**How the v2.1 factors are built.** `gasConvenience` blends the nearest gas station or convenience store (70%) with how many are within 500 m (30%). The noise corridor adds an adjacency penalty from gas stations and convenience stores to the corridor signal: full within 300 ft, fading linearly to none at 800 ft. `shopping` is 60% proximity (to the third-nearest shop) and 40% variety of retail types within a mile, plus the brand bonus. `recreation` is 75% parks (proximity to the nearest park and the size of the largest one within half a mile) and 25% running trails. `school` is 20% proximity and 80% district rating, and `null` where no rating exists (see [data-sources.md](data-sources.md)). The API serves only rows matching its configured weights version (`SCORING_WEIGHTS_VERSION`, `v2-handtuned` in production), so rows from another version are never mixed in. Brand matching for the shopping bonus uses the OpenStreetMap `brand:wikidata` tag (Whole Foods Q1809448, Starbucks Q37158 and Starbucks Reserve Q71150001, Target Q1046951), with a name fallback.

**Known limitation (v3 candidate).** Each factor is min-max normalized within its metro area, so a few extreme outlier distances stretch the scale and skew everyone else's scores. A visible symptom: remote cells with very little around them can still score high on `restaurant` and `bar`. A more robust normalization (percentile or log-scaled distances) is a scoring v3 candidate; see `docs/ROADMAP.md`.

**Noise corridor.** The `emergencyCorridor` factor is displayed as "Noise corridor": main roads near fire stations, hospitals and police stations, where sirens and through-traffic noise are most likely, plus (v2.1) gas stations and convenience stores right next door. It is a rough proxy (default weight 12 of 106 in v2.1). The API key `emergencyCorridor` and the database columns keep their names.


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
| `precision` | `grid` \| `point` | no | `grid` (default) returns the stored score of the containing cell. `point` scores the exact location on demand (see [SCORING.md](SCORING.md) A8) and falls back to `grid` on any error; the response's `precision` field says which was served. `/area` accepts it too and scores the mean of up to five points inside the polygon. |

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
    "shopping": 100.0,
    "gasConvenience": null,
    "transit": 99.9,
    "school": null,
    "traffic": 89.0,
    "emergencyCorridor": 96.5,
    "airport": 63.4,
    "recreation": 79.8
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

### `neighborhood`

`/score`, `/area`, each `/map/top` result, `/similar` results, and `/improve`'s `betterArea` and `bestNearby` (and `/area/explanation`) carry `neighborhood`: a human name such as `"Park Slope, Brooklyn"` or `"Montclair, NJ"`, or `null`. It is built from OpenStreetMap place nodes by `python -m ingestion.neighborhoods` (migration 0008): the nearest neighbourhood/suburb/quarter within 1.2 mi, else the nearest village/town/hamlet within 3 mi, else a city within 8 mi; the suffix is the NYC borough, else the nearest city/town, else the state (NY/NJ/CT). It is never coordinates. It is `null` before the job has run or when no place is nearby; clients should fall back to `address` / `areaLabel`. For `/area` it is the area's own label, else the label of the cell under the point. The examples below were captured before the job ran, so they omit or null it.

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

Score for the whole **road-bounded area** under a point: the block of land enclosed by secondary-and-larger roads (secondary, primary, trunk, motorway) and the shoreline. The website calls this when you click the map and draws the polygon; areas are capped at 0.8 square miles and 1.4 miles across (larger road-bounded blocks are cut into roughly 0.75 mile tiles, tiny ones merged into a neighbour at build time); on a 404 it falls back to the single grid cell. Sub-scores are the area-weighted average of the latest scores of the geohash6 cells the area overlaps, skipping cells that lack a given factor. `compositeScore` is the area-weighted average of those cells' composite scores (what the map shows), so it can differ slightly from recomputing a composite from the averaged sub-scores. Results are cached for 5 minutes.

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
    "shopping": 43.4, "gasConvenience": null, "transit": 99.2,
    "school": null, "traffic": 93.0, "emergencyCorridor": 98.0, "airport": 42.4,
    "recreation": 82.2
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
| 404 | `area_not_found` | No area contains or is within 40 m of the point, the only matching area is larger than 0.8 square miles or wider than 1.4 miles (legacy polygons), no cell has a score, or areas have not been built yet. Fall back to `GET /score?lat=&lon=` |
| 422 | `out_of_coverage` | The point is outside the covered metro area |

## `GET /area/explanation`

The explanation for the road-bounded area under a point, written by the LLM layer when available and rule-based otherwise. It resolves the area exactly as `GET /area` does; it is a separate endpoint so `/area` stays fast and never waits on an LLM call. Results are cached for 5 minutes (and AI text is cached server-side).

| Parameter | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `lat` | query | number | yes | Latitude, inside the covered area |
| `lon` | query | number | yes | Longitude, inside the covered area |
| `factors` | query | string | no | Comma-separated factor keys the user cares about (same keys as `/map/top`). Omit for all 13 factors. |
| `weights` | query | string | no | Optional importance overrides as `factor:number,...`, same as `/map/top` |

```bash
curl "https://api.benrispace.com/v1/area/explanation?lat=40.672&lon=-73.978"
```

Example response (invented, for shape only; not captured from production):

```json
{
  "explanation": "This area scores 77 overall, driven by excellent transit and everyday amenities close by. Strengths: transit access 99; cafe access 98. Weaknesses: distance from convenience stores is only 2.",
  "source": "ai",
  "areaId": 5432,
  "neighborhood": "Park Slope, Brooklyn",
  "priorities": ["grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience", "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation"]
}
```

With `factors` the text speaks to those priorities first. The AI text (prompt version `expl-v2`) is written from an evidence packet: the selected factors, every factor's score with where it sits in the metro (for example "top 3% of the metro"), the neighborhood name (or, without one, the road-bounded area name), up to two named nearby places per selected place-based factor with distances in feet or miles, and the selected factors that are strongest and weakest against the metro median. It names at least two of those places when they exist, states one tradeoff ("Tradeoff: ...") and one suggestion ("Tip: ..."), and runs 60 to 90 words. A reply is accepted only if every number comes from the evidence, only feet and miles are used, every capitalised proper noun is in the evidence (place and street names), and praise words such as "excellent" appear only for a selected factor in the top 5% of the metro; otherwise the rule-based text is returned, which also leads with the selected priorities. The server-side cache key includes the sorted selected factors.

`source` is `"ai"` or `"rules"` (the same rule-based text `/area` returns in its `explanation` field). Errors are the same as `GET /area`: 400 `invalid_request`, 404 `area_not_found`, 422 `out_of_coverage`.

## `GET /score/{geoEntityId}/explanation`

A short plain-language explanation of one score: the strongest factor, the weakest, the rest, and (when known) the distance to the nearest feature for the strongest and weakest. The text is written by an LLM, constrained to the stored scores and distances (every number in it must come from them, and only feet and miles are used), and falls back to the rule-based text (`api/explain.py`) whenever the LLM is unavailable, over budget or fails validation. The `source` field says which one you got: `"ai"` or `"rules"`.

| Parameter | In | Type | Description |
| --- | --- | --- | --- |
| `geoEntityId` | path | UUID | The `geoEntityId` from a `/score` response |
| `factors` | query | string | no | Comma-separated factor keys the user cares about (same keys as `/map/top`). Omit for all 13 factors. |
| `weights` | query | string | no | Optional importance overrides as `factor:number,...`, same as `/map/top` |

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

(The text above is the rule-based explanation captured from production for this cell, so `source` would be `"rules"`; the response also carries `source`, `priorities` (the factor keys used, as on `/area/explanation`) and `nearestMi`, described next. `factors`/`weights` work exactly as on `/area/explanation`.)

Distances in the text are in feet and miles. The response also carries `nearestMi`, the distance in miles to the nearest feature per factor (a number, or `null` when unknown), for the factors that have one: `grocery`, `gym`, `cafe`, `restaurant`, `bar`, `gasConvenience` (the nearest gas station or convenience store), `transit`, `school`, `recreation` (the nearest park or trail), `shopping` (the nearest shop, or Whole Foods, Starbucks or Target) and `emergencyCorridor` (the nearest emergency facility). `traffic` and `airport` are not included. Where a distance is unknown the value is `null`, and the explanation omits its "Nearest feature" sentence. Shape:

```json
{ "nearestMi": { "grocery": 0.2, "gym": null, "shopping": 0.8 } }
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

## `POST /optimize`

Finds the places to live that minimise your weekly travel to several destinations, for example "near my work (123 Main St, Stamford), a Trader Joe's and a Planet Fitness". Each anchor is an `address` (geocoded, or pass `latitude`/`longitude`), a `brand` (case-insensitive match on a place's name or brand, so `trader joe` finds "Trader Joe's") or a `category` (`grocery`, `gym`, `cafe`, `restaurant`, `bar`, `transit`, `school`, `gas_station`, `convenience_store`, plus synonyms such as `coffee`, `groceries`, `gas`). For brands and categories each candidate uses its nearest matching place.

Candidates are grid cells within `radiusMi` of the centroid of the address anchors (or of all brand matches when there is no address). Weekly cost is the sum over anchors of `tripsPerWeek` x 2 (round trip) x minutes. Results are ranked by cost, ties broken by the overall score for your `factors`/`weights`, and kept at least 1 mi apart.

Minutes are first estimated (straight line x 1.3, walking 3 mph, driving 25 mph plus 2 min, transit 15 mph including waits). The best ~25 candidates are then re-timed with live routing for walk and drive anchors; if routing is unavailable, estimates are kept. Each anchor result says which with `approx`. Transit is always estimated for now ("train times arrive with the transit precompute").

Request body (JSON):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `anchors` | array, 1-6 items | yes | Destinations |
| `anchors[].kind` | `address` \| `brand` \| `category` | yes | What `query` is |
| `anchors[].query` | string | yes | Address, brand/place name or category word |
| `anchors[].latitude`, `anchors[].longitude` | number | no | Address anchors only; skips geocoding |
| `anchors[].tripsPerWeek` | number | no | Default 5 for the first address (work), 3 for gyms, 1 otherwise |
| `anchors[].mode` | `walk` \| `drive` \| `transit` | no | Default `defaultMode` |
| `defaultMode` | `walk` \| `drive` \| `transit` | no | Default `drive` |
| `radiusMi` | number | no | Default 15, max 30 |
| `limit` | integer 1-10 | no | Default 3 |
| `factors`, `weights` | string or array / object | no | Priorities for the tie-break score, as on `/map/top` |

**Invented example, shape only: the numbers are made up, not captured from production.**

```bash
curl -X POST "https://api.benrispace.com/v1/optimize" \
  -H "Content-Type: application/json" \
  -d '{
    "anchors": [
      {"kind": "address", "query": "123 Main St, Stamford, CT"},
      {"kind": "brand", "query": "trader joe"},
      {"kind": "brand", "query": "planet fitness"}
    ],
    "limit": 1
  }'
```

```json
{
  "results": [
    {
      "latitude": 41.0612,
      "longitude": -73.5441,
      "neighborhood": null,
      "areaLabel": null,
      "weeklyMinutes": 121,
      "score": 74,
      "anchors": [
        {"query": "123 Main St, Stamford, CT", "kind": "address", "name": "123 Main St, Stamford, CT",
         "latitude": 41.0534, "longitude": -73.5387, "minutes": 9, "distanceLabel": "0.6 mi", "mode": "drive", "approx": false},
        {"query": "trader joe", "kind": "brand", "name": "Trader Joe's",
         "latitude": 41.0701, "longitude": -73.5532, "minutes": 7, "distanceLabel": "0.9 mi", "mode": "drive", "approx": false},
        {"query": "planet fitness", "kind": "brand", "name": "Planet Fitness",
         "latitude": 41.0655, "longitude": -73.5498, "minutes": 5, "distanceLabel": "0.4 mi", "mode": "drive", "approx": false}
      ]
    }
  ],
  "assumptions": ["Assumed 5 work trips/week by car", "Assumed 1 trips/week to trader joe by car", "Assumed 3 trips/week to planet fitness by car"],
  "unresolved": []
}
```

`neighborhood` is `null` until neighborhood names are loaded. Anchors that cannot be resolved (unknown address, no matching place nearby, unknown category) are listed in `unresolved` and left out of the ranking; `results` is empty when nothing can be ranked. Distances are in feet and miles.

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Bad anchors, `radiusMi`, `limit`, `factors` or `weights`; or only category anchors (nothing to search around) |
| 422 | `out_of_coverage` | An address anchor is outside the covered metro area |

---

## `POST /chat`

"Ask Benri": a short chat that finds and explains neighborhoods. The model (Claude Haiku 4.5) can only call our own read-only tools (`geocode`, `area_score`, `nearby_places`, `improve`, `similar`, `search_areas`, `find_places`, `optimize_location`) and may only state what their results, or the user's own messages, contain. The client keeps the conversation and sends it with every request; only the last 6 messages (each cut to 2,000 characters) are used.

Request body (JSON):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `messages` | array | yes | `{role: "user" \| "assistant", content: string}`; must end with a `user` message |
| `context.address` | string | no | The place the user has selected |
| `context.latitude`, `context.longitude` | number | no | Its coordinates (tools default to searching near it) |
| `context.factors` | array of factor keys | no | The user's selected priorities (tools default to them) |
| `context.weights` | object | no | Importance per factor |

Response:

| Field | Type | Description |
| --- | --- | --- |
| `reply` | string | Plain text, at most about 120 words. Numbers and capitalised names are checked against the tool results; if the check fails the reply is replaced by a short deterministic summary and `limited` is `true` |
| `results` | array, at most 3 | Built from the last ranking tool (`optimize_location`, `search_areas` or `similar`), never by the model: `label` (neighborhood or area label), `latitude`, `longitude`, `score?`, `weeklyMinutes?`, `why` |
| `sources` | array | `{tool, summary}` for each tool the assistant used |
| `limited` | boolean | Present and `true` when the reply is a fallback or chat is paused |

The assistant declines off-topic requests and does not characterize who lives somewhere or answer crime, safety or demographics questions (BenriSpace has no such data); it offers the 13 factors instead. Anything it quotes is in feet and miles.

**Invented example, shape only.**

```bash
curl -X POST "https://api.benrispace.com/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Is Park Slope good for transit and groceries?"}]}'
```

```json
{
  "reply": "Yes. Park Slope, Brooklyn scores 98 on transit and 98 on grocery access.",
  "results": [],
  "sources": [{"tool": "geocode", "summary": "Located Park Slope, Brooklyn, NY"}, {"tool": "area_score", "summary": "Scores for Park Slope, Brooklyn"}]
}
```

Limits: each visitor (a salted hash of the client IP, never stored raw) gets 15 messages a day, tracked in the `chat_usage` table (migration 0010; the limit is skipped while the table is absent). Calls count against the monthly LLM budget (`LLM_MONTHLY_BUDGET_USD`, logged in `llm_usage` with kind `chat`); when it is spent the endpoint answers `"Chat is paused for this month."` with `limited: true`.

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Empty `messages`, a bad factor key, or the last message is not from the user |
| 429 | `rate_limited` | The visitor has used today's 15 messages |
| 503 | `chat_unavailable` | No `ANTHROPIC_API_KEY` is configured, or the model call failed or timed out |

---

## `POST /chat/stream`

The same request body, tools, limits and answer as [`POST /chat`](#post-chat), delivered as server-sent events (`Content-Type: text/event-stream`). A malformed body is rejected with a plain `400` before the stream starts; everything after that arrives as frames:

```text
event: status
data: {"text":"Searching areas","tool":"search_areas"}

event: reply
data: {"reply":"...","results":[],"sources":[]}
```

| Event | Data | When |
| --- | --- | --- |
| `status` | `{text, tool?}` | Zero or more times while the assistant thinks or runs a tool |
| `reply` | The `POST /chat` response body | Exactly once on success. The text is sent whole, after the grounding check |
| `error` | `{status, code, message}` | Instead of `reply`, with the codes in the table above (`429`, `503`) |

Lines starting with `:` are keep-alive comments. Behind API Gateway the frames arrive together when the answer is done; they stream live only through a Lambda function URL (see [ARCHITECTURE.md](ARCHITECTURE.md), "Chat streaming"). The web app uses it only when `NEXT_PUBLIC_CHAT_STREAM_URL` is set.

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

## `GET /places`

The nearest named places for one factor, for "what is nearby" lists. Distances are in feet (under 0.1 mi) or miles; there are no metric fields. `gasConvenience` merges gas stations and convenience stores, nearest first; `shopping` returns named shops and `recreation` named parks (OpenStreetMap, ingested by `ingestion/osm_retail_parks.py`). The legacy `premiumRetail` still merges Whole Foods, Starbucks and Target, nearest first. Results are cached for 5 minutes.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `lat` | number | yes | Latitude, inside the covered area |
| `lon` | number | yes | Longitude, inside the covered area |
| `factor` | string | yes | One of `grocery`, `gym`, `cafe`, `restaurant`, `bar`, `shopping`, `recreation`, `gasConvenience`, `transit`, `school`; the legacy `gasStation`, `convenienceStore` and `premiumRetail` also work |
| `radiusMi` | number | no | Search radius in miles, above 0 and up to 5. Default 1 |
| `limit` | integer | no | 1 to 20 places. Default 5 |

```bash
curl "https://api.benrispace.com/v1/places?lat=40.758&lon=-73.9855&factor=cafe&radiusMi=0.5&limit=2"
```

Example response (invented for illustration, not a captured production response):

```json
{
  "factor": "cafe",
  "radiusMi": 0.5,
  "places": [
    { "name": "Culture Espresso", "brand": null, "category": "cafe", "distanceMi": 0.05, "distanceLabel": "250 ft", "direction": "NE", "latitude": 40.7585, "longitude": -73.9849 },
    { "name": "Starbucks", "brand": "Starbucks", "category": "cafe", "distanceMi": 0.31, "distanceLabel": "0.3 mi", "direction": "S", "latitude": 40.7537, "longitude": -73.9859 }
  ]
}
```

With `factors`, `composite` and `bestNearby` use the composite of the selected factors only (weighted average of the selected factors' non-null scores, for the area and for every neighbouring cell) instead of the stored overall composite. `priorities` lists the factor keys used. If no selected place-based factor is below 75, `suggestions` is `[]`, and `bestNearby` is still returned when a neighbouring cell gains at least 3 on the selected composite.

`places` is an empty list when nothing is within the radius.

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing or invalid `lat`/`lon`, unknown `factor`, `radiusMi` outside (0, 5], or `limit` outside 1..20 |
| 422 | `out_of_coverage` | The point is outside the covered metro area |

---

## Priorities (`factors`)

`/improve`, `/similar`, `/area/explanation` and `/score/{geoEntityId}/explanation` accept the same optional `factors` (and `weights`) query parameters as `/map/top`: the factors the user selected, for example `factors=grocery,transit,cafe`. Everything those endpoints say is then about those factors only. Weights default to the scoring weights restricted to the selected factors and renormalised, and a missing (`null`) score is ignored. Each response echoes the factors it used in `priorities`. Omitting `factors` means all 13 factors, and the endpoints keep their previous behaviour. Legacy keys (`premiumRetail`, `trailPopularity`, `road`, `gasStation`, `convenienceStore`) are accepted as aliases.

---

## `GET /improve`

Deterministic "what could improve this score" suggestions for the area under a point. It finds the weakest place-based factors among the selected ones (grocery, gym, cafe, restaurant, bar, shopping, recreation, gasConvenience, transit, school; a score below 75, lowest first), and for each lists nearby named places and the best neighbouring cell that scores at least 10 points higher on that factor. Traffic, noise corridor and airport are not place-based and are never suggested. Nothing is generated or guessed: every sentence comes from stored scores and places. Distances are in feet (under 0.1 mi) or miles; there are no metric fields. Results are cached for 5 minutes.

The point is resolved like `/area` (the road-bounded area's score). If no area is found there, the grid cell's own score is used instead.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `lat` | number | yes | Latitude, inside the covered area |
| `lon` | number | yes | Longitude, inside the covered area |
| `radiusMi` | number | no | Search radius in miles, above 0 and up to 3. Default 1 |
| `maxSuggestions` | integer | no | 1 to 5 factors. Default 3 |
| `factors` | string | no | Comma-separated factor keys the user cares about (same keys as `/map/top`). Omit for all 13 factors. Must not be empty if present; an unknown key is a 400. |
| `weights` | string | no | Optional importance overrides as `factor:number,...`, same as `/map/top` |

```bash
curl "https://api.benrispace.com/v1/improve?lat=40.758&lon=-73.9855&maxSuggestions=2"
```

Example response (invented for illustration, not a captured production response):

```json
{
  "composite": 68.4,
  "radiusMi": 1.0,
  "suggestions": [
    {
      "factor": "grocery",
      "label": "Grocery",
      "score": 41,
      "places": [
        { "name": "Aldi", "brand": "Aldi", "distanceMi": 0.31, "distanceLabel": "0.3 mi", "direction": "W", "latitude": 40.758, "longitude": -73.9911 }
      ],
      "betterArea": { "latitude": 40.7641, "longitude": -73.9855, "direction": "N", "distanceMi": 0.42, "distanceLabel": "0.4 mi", "factorScore": 66, "factorGain": 25, "compositeScore": 72, "compositeGain": 4, "neighborhood": "Park Slope, Brooklyn" },
      "tip": "Grocery is your weakest factor (41). The closest option is Aldi, 0.3 mi west. Park Slope, about 0.4 mi north, scores 66 on grocery."
    }
  ],
  "bestNearby": { "latitude": 40.7641, "longitude": -73.9855, "direction": "N", "distanceLabel": "0.4 mi", "compositeScore": 72, "compositeGain": 4, "neighborhood": "Park Slope, Brooklyn" },
  "priorities": ["grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience", "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation"]
}
```

`places` is an empty list when nothing is within the radius, `betterArea` is `null` when no neighbouring cell gains 10 points, and `bestNearby` is `null` when no neighbouring cell raises the composite by at least 3. `suggestions` is empty when no factor is below 75. Up to 3 places are returned per factor. Gains are whole numbers. `neighborhood` (on `betterArea` and `bestNearby`) is `null` when unlabelled; the tip then says "The area about 0.4 mi north ...".

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing or invalid `lat`/`lon`, `radiusMi` outside (0, 3], `maxSuggestions` outside 1..5, or an invalid `factors`/`weights` |
| 404 | `area_not_found` | No area and no scored cell for this location |
| 422 | `out_of_coverage` | The point is outside the covered metro area |

---

## `GET /similar`

Areas elsewhere in the same metro with a similar factor profile. Each scored cell has a 14-dimension vector (one z-scored sub-score per factor, a missing school score counts as average), stored in pgvector. The nearest vectors are found in the database, then spread out: results closer than `minSeparationMi` to the point or to an earlier result are dropped, so you get distinct places rather than a cluster of neighbouring cells. Distances are in feet (under 0.1 mi) or miles; there are no metric fields. Results are cached for 5 minutes.

With `factors`, the closest 200 vectors are re-ranked by straight-line distance over only the selected factors (z-scored with the metro's mean and standard deviation, the same as the stored vectors, loaded once per server process; a missing score counts as average; `weights` scale each factor's share), and then the spacing rule is applied. `similarity` is rescaled so it stays comparable with the unfiltered value.

Requires migration `0007_embeddings.sql` and a run of `python -m scoring.embeddings` (part of the weekly score job). Until then every request returns 404. Neighbours come from pgvector's HNSW index (`hnsw.ef_search` sized to the pool, iterative scan where available); with migration `0011_perf.sql` the embeddings job also stores each cell's top 20 neighbours in `similar_cells`, which answer unfiltered requests directly when they yield enough spread-out results.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `lat` | number | yes | Latitude, inside the covered area |
| `lon` | number | yes | Longitude, inside the covered area |
| `k` | integer | no | Number of results, 1 to 10. Default 5 |
| `minSeparationMi` | number | no | Minimum spacing in miles from the point and between results, 0 to 10. Default 1 |
| `factors` | string | no | Comma-separated factor keys the user cares about (same keys as `/map/top`). Omit for all 13 factors. Must not be empty if present; an unknown key is a 400. |
| `weights` | string | no | Optional importance overrides as `factor:number,...`, same as `/map/top` |

```bash
curl "https://api.benrispace.com/v1/similar?lat=40.758&lon=-73.9855&k=3"
```

Example response (invented for illustration, not a captured production response):

```json
{
  "minSeparationMi": 1.0,
  "results": [
    {
      "latitude": 40.6892,
      "longitude": -73.9442,
      "direction": "SE",
      "distanceLabel": "6.1 mi",
      "similarity": 88,
      "compositeScore": 71,
      "areaLabel": "Area bounded by Nostrand Ave, Atlantic Ave and Bedford Ave",
      "differences": [
        { "factor": "transit", "label": "transit", "delta": 14 },
        { "factor": "emergencyCorridor", "label": "noise", "delta": -12 }
      ],
      "summary": "14 points better for transit, 12 points weaker for noise."
    }
  ],
  "priorities": ["grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience", "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation"]
}
```

`similarity` is a whole number from 0 to 100: `100 * max(0, 1 - distance / 6)`, where `distance` is the straight-line gap between the two vectors. `differences` lists up to 3 selected factors where the result's score differs from the point's by at least 6, largest gap first; `delta` is signed (positive means the result scores higher, which is always better). `summary` is built from `differences`, or reads "Very similar across all factors." when there are none. `areaLabel` is the road-bounded area containing the result, or `null` when there is none; `neighborhood` is its human name (for example `"Crown Heights, Brooklyn"`), or `null`. `results` can hold fewer than `k` entries when the spacing rule leaves too few.

Errors:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing or invalid `lat`/`lon`, `k` outside 1..10, `minSeparationMi` outside 0..10, or an invalid `factors`/`weights` |
| 404 | `not_found` | The cell under the point has no embedding (or no score) yet |
| 422 | `out_of_coverage` | The point is outside the covered metro area |

---

## `GET /map/cells`

Composite score for every grid cell inside a map viewport, calculated for the factors and weights you choose. It is a weighted average of the stored sub-scores (not a recalculation from raw data), so it is cheap to call whenever the user toggles a filter.

For each cell, the composite uses only the selected factors that are not `null` for that cell, so the denominator counts only the weights of factors that have data; cells where every selected factor is `null` are left out.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `bbox` | string | yes | Viewport as `minLon,minLat,maxLon,maxLat`. Cells whose grid point lies inside are returned. |
| `precision` | integer | no | `6` (default, about 0.6 x 0.4 mile cells) or `5` (about 2.3 x 3 miles; the mean of the finer cells). Use 5 when zoomed out. |
| `factors` | string | no | Comma-separated factor keys to include, for example `transit,cafe`. Omit for all thirteen (legacy keys are accepted as aliases); an explicit list means exactly those factors. Must not be empty if present. |
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
  "weights": { "grocery": 14, "gym": 9, "cafe": 8, "restaurant": 10, "bar": 5, "shopping": 4, "gasConvenience": 6, "transit": 14, "school": 10, "traffic": 4, "emergencyCorridor": 12, "airport": 5, "recreation": 5 },
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
{ "code": "invalid_request", "message": "unknown factor 'foo'; valid factors: grocery, gym, cafe, restaurant, bar, shopping, gasConvenience, transit, school, traffic, emergencyCorridor, airport, recreation" }
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

You get up to `limit` results, fewer if the area (or the separation) leaves no more candidates. Each result has `geohash`, `latitude` and `longitude` (the cell's grid point), `score` (rounded to one decimal), `metroArea`, and the full `subScores` object for the cell (all thirteen factors, whatever you selected for the ranking).

```bash
curl "https://api.benrispace.com/v1/map/top?limit=2"
```

With no `factors` or `weights`, all thirteen factors and their default weights are used (real response, rounded; the sub-scores are shown on one line each for space):

```json
{
  "factors": ["grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience", "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation"],
  "weights": { "grocery": 14, "gym": 9, "cafe": 8, "restaurant": 10, "bar": 5, "shopping": 4, "gasConvenience": 6, "transit": 14, "school": 10, "traffic": 4, "emergencyCorridor": 12, "airport": 5, "recreation": 5 },
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
        "shopping": 62.6, "gasConvenience": null, "transit": 98.4,
        "school": 89.9, "traffic": 90.9, "emergencyCorridor": 99.7, "airport": 95.2,
        "recreation": 98.5
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
        "shopping": 56.5, "gasConvenience": null, "transit": 96.2,
        "school": 95.0, "traffic": 97.9, "emergencyCorridor": 100.0, "airport": 88.2,
        "recreation": 89.4
      }
    }
  ]
}
```

Note the second result: a spot at 40.97 N is far from the dense core yet scores 87 on `bar` and 96 on `restaurant`. That is the min-max normalization weakness described under "What a score means" (a v3 candidate), not a real nightlife hub.

Errors: the same `400 invalid_request` cases as `/map/cells` for `bbox`, `factors` and `weights`, plus `limit` outside 1-50, `minSeparationMi` outside 0-31 (or `minSeparationKm` outside 0-50), or both separation parameters at once. The response has no separation field; the spacing is applied, not echoed.

---

## `GET /map/scores`

Every cell's 13 sub-scores for the configured weights version in one compact binary file, so a browser can recompute the composite locally for any factor or importance change with no further API calls. `version` is optional; if given it must equal the served weights version (otherwise 404). Cached for a day (`Cache-Control: public, max-age=86400`); `ETag` is `"<version>-<max computed_at as unix seconds>"` and a matching `If-None-Match` returns `304`. Sent gzip-encoded when the client accepts it (`Vary: Accept-Encoding`). About 1.2 MB raw for 64,320 cells (19 bytes a cell), built from one SQL query and cached per server process by ETag.

`Content-Type: application/octet-stream`. All integers are little-endian. Layout:

| Part | Size | Content |
| --- | --- | --- |
| `headerLength` | 4 bytes | `uint32`, byte length of the header JSON |
| header | `headerLength` bytes | UTF-8 JSON: `{"format":1,"version":"v2-handtuned","factors":[13 keys],"count":N,"geohashLength":6,"generatedAt":"<ISO 8601>"}` |
| geohashes | `N * 6` bytes | fixed 6-character ASCII geohashes, sorted ascending, no separators |
| scores | `N * 13` bytes | `uint8`, cell-major: cell `i`, factor `j` is at `i * 13 + j`; `0` to `100` rounded half up, `255` means no score |

`factors` gives the column order (the same keys as `/map/top`: grocery, gym, cafe, restaurant, bar, shopping, gasConvenience, transit, school, traffic, emergencyCorridor, airport, recreation). A cell's composite for chosen factors is `sum(w_j * s_j) / sum(w_j)` over the chosen factors whose byte is not `255`, exactly as `/map/cells` computes it (up to the rounding of each sub-score to a whole number).

Decoder (Python):

```python
import json, struct
def decode(blob):
    (hlen,) = struct.unpack_from("<I", blob, 0)
    h = json.loads(blob[4:4 + hlen]); n, w, f = h["count"], h["geohashLength"], len(h["factors"])
    p = 4 + hlen
    hashes = [blob[p + i*w:p + (i+1)*w].decode() for i in range(n)]
    p += n * w
    return h, hashes, [[None if b == 255 else b for b in blob[p + i*f:p + (i+1)*f]] for i in range(n)]
```

| Status | `code` | When |
| --- | --- | --- |
| 304 | | `If-None-Match` matches the current `ETag` |
| 404 | `not_found` | Unknown `version`, or no scores for the served version |

---

## `GET /sources`

Data transparency: where the scores come from. Each entry has `id`, `name`, `feeds` (what it feeds), `license`, `url`, `lastUpdated` (latest successful ingestion finish across the jobs that refresh it, or `null`) and `rowsAffected` (their summed rows, or `null`). The registry is static (`api/sources.py`); freshness comes from `ingestion_runs`. Cached for an hour.

```json
{ "sources": [ { "id": "osm_poi", "name": "OpenStreetMap points of interest", "feeds": "Grocery, gym, ...", "license": "ODbL 1.0 (c) OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright", "lastUpdated": "2026-10-01T04:12:09Z", "rowsAffected": 101690 } ] }
```

---

## `POST /feedback`

Thumbs and reports from the app. Body: `kind` (`summary`, `chat` or `place`), optional `target` (up to 200 characters; a geohash, message id or place name), optional `rating` (`-1`, `0` or `1`) and optional `message` (up to 1000 characters). Returns `204` with no body. Each anonymous visitor (salted hash of the client IP, never stored raw) may send 30 a day; beyond that the response is `429 rate_limited`. Requires migration `0011_perf.sql`; until it is applied the item is logged and dropped and the response is still `204`. An invalid body is a 400.

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
