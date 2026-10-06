# BenriSpace Scoring

How a location's 0-100 score is computed. Two parts:

- **Part A: what is shipped.** The models built: `v2-handtuned` and `v2.1-handtuned`
  (served). `v1-handtuned` was retired and its rows deleted.
- **Part B: the v3 framework (planned).** `v3-timeaccess`, framework v1.4 with the
  owner's decisions. Nothing in Part B is serving yet, except the default weights
  and factor set, which v2.1 already uses. Section numbers inside Part B refer to
  Part B.

Related: [ARCHITECTURE.md](ARCHITECTURE.md), [ROADMAP.md](ROADMAP.md),
[api.md](api.md) (factor keys and responses), [data-sources.md](data-sources.md).

---

# Part A: shipped model (v1, v2, v2.1)

## A1. Status

Stored scores are whole points: sub-scores are `smallint` (0-100) and the composite is `real` with one decimal (migration 0017), which is what every reader displays anyway.

| Version | `weights_version` | Factors | State |
| --- | --- | --- | --- |
| v1 | `v1-handtuned` | 11 | retired; rows deleted from the database |
| v2 | `v2-handtuned` | 14: 12 toggleable plus 2 underlying signals | retired; rows deleted from the database |
| v2.1 | `v2.1-handtuned` | 13, all user-facing pills | **live in production**; per-metro relative scales |
| v2.2 | `v2.2-density` | 13, same pills and default weights | built; scored per area from routed travel times on one absolute scale (A10); cutover pending |

Rollback is a Terraform variable (`scoring_weights_version`). The API reports the
version that produced a response in `weightsVersion`. A new version gets new rows
rather than overwriting, so history is never lost. Rows with the same
`weights_version` are replaced by a re-run, and the score writer nulls stale
columns.

Hand-tuned weights, because there is no training data to fit against yet. Weight
rationale lives next to the weights in `scoring/engine.py` (`DEFAULT_WEIGHTS`,
`V2_1_WEIGHTS`); it is the defensibility story for users and a baseline for any
future learned model.

## A2. Normalization

Each raw metric (count or distance) is min-max normalized to 0-100 **within its
`metro_area` cohort**, not globally. v1 spans dense city and suburban or exurban
areas (Hudson Valley, Fairfield County); a global scale would flatten every
suburban address to near zero on walkability-shaped factors. The product scores
convenience relative to the kind of area an address is in.

```
normalized = (x - min) / (max - min) * 100
```

Distance-based metrics are inverted first (closer is better):
`x_for_normalization = -distance`.

Sign is applied **before** normalization, at ingestion time, so every value that
flows into `scores` already means "higher is better":

| Raw signal | Direction | Handling |
| --- | --- | --- |
| grocery, gym, cafe count and closeness | Positive | normalize as-is |
| restaurant (`amenity=restaurant`), bar (`bar`, `pub`, `biergarten`) | Positive | as-is (70% proximity / 30% density, like other POIs) |
| transit stop count and closeness | Positive | as-is |
| school count, rating, closeness | Positive | as-is (see A4) |
| running trail count and closeness, Strava popularity | Positive | as-is (see A5) |
| premium retail (Whole Foods, Starbucks, Target) | Positive | one `premium_retail_raw` bonus built at ingestion from the three `*_nearest_ft` columns |
| airport drive time | Positive | invert (lower time is better) |
| gas station / convenience store count (v2) | Negative | invert before normalizing |
| congestion proxy | Negative | invert before normalizing |
| noise corridor (key `emergencyCorridor`) | Negative | invert, then reduced by `street_orientation` (a side street dampens the penalty; facing the corridor does not). Uses `emergency_corridor_facility_raw` (fire, police and EMS facility count and closeness); where that is null it falls back per cell to the v1 `emergency_corridor_proxy_raw` |

**Noise corridor** is the user-facing name of the `emergency_corridor_score`
factor (API key `emergencyCorridor`; DB columns unchanged): main roads near fire
stations, hospitals and police stations, where sirens and through-traffic noise
are most likely. A rough proxy.

## A3. Composite

```
composite_score = sum(weight_i * subscore_i) / sum(weight_i)
```

over the factors that have a score. A `null` factor is left out of both sums,
never counted as 0, so the result is always out of 100. v2 weights: grocery 1.5,
gym 1.0, cafe 1.0, restaurant 1.0, bar 0.5, premium retail 0.75, gas station 1.0,
convenience store 0.75, transit 1.5, school 1.5, road 1.0, noise corridor 0.75,
airport 0.75, trail popularity 1.25 (v1 had 11 factors with noise corridor 0.5 and
without restaurant, bar and premium retail).

Users can choose factors and weights (`/map/cells`, `/map/top`, the web filters and
presets); the overall is then normalized to the weight of the selected factors
that have a score (the same rule as Part B section 2.1).

## A4. Schools

School proximity-plus-density and school rating are each min-max normalized, then
blended **20% proximity / 80% rating**. With **no rating**, `school_score` is
`NULL`, never a proximity-only substitute, so the factor drops out of the
composite. The engine still writes `school_proximity_score` for every cell with
school data (informational, not a composite factor) so clients can say
"proximity 72, rating unavailable". `school_district_*` and `school_rating_source`
record where a rating came from. Ratings are district-level only
([data-sources.md](data-sources.md)).

## A5. Trails and Strava

Running trail popularity is built from mapped OSM running trails (free,
required). Strava segment popularity is an optional enrichment that is **not
configured**: `strava_segment_popularity_raw` is `null` (never 0) when Strava is
absent, and the factor normalizes off the OSM trail count and distance alone
(67/33 blend in `scoring/engine.py`). Never backfill a missing value with 0: that
would read as "definitely unpopular". Garmin was considered and dropped (no
public API exposes aggregate route popularity). Strava's rate limits (about 100
calls per 15 minutes, 1,000 a day) make the enrichment take up to about 150
minutes per weekly run, which on a private repo costs real Actions minutes.

## A6. v2.1 (`v2.1-handtuned`)

Every factor is a user-facing pill (13, none hidden). Same min-max engine shape,
with these changes (`CATEGORY_SPECS_V2_1` in `scoring/engine.py`):

| API key | `scores` column | Raw signal (higher is better) |
| --- | --- | --- |
| `shopping` | `shopping_score` | `shopping_raw` (0.6 proximity to the 3rd-nearest shop + 0.4 variety of retail groups within 1 mi; `ingestion/osm_retail_parks.py`) + 0.08 x `premium_retail_raw` anchor bonus |
| `gasConvenience` | `gas_convenience_score` | one positive factor: the 70/30 nearest/count blend over the union of gas stations and convenience stores |
| `emergencyCorridor` | `emergency_corridor_score` | negative: the corridor/facility raw signal (damped for side streets) plus an adjacency penalty from the nearest gas station and nearest convenience store (full within 300 ft, linear to 0 at 800 ft) |
| `traffic` | `road_score` | unchanged (renamed in the UI and API only) |
| `recreation` | `recreation_score` | 75% `recreation_raw` (parks: 2/3 proximity + 1/3 size of the largest park within half a mile) + 25% the existing trail count/closeness signal, each normalized separately |

The gas station and convenience store columns feed two factors at different
distances: a positive `gasConvenience` and a negative adjacency term inside the
noise corridor. New `feature_store` columns are imperial (`shopping_nearest_ft`,
`park_largest_sq_ft_half_mi`, ...), migration `0009_v2_1.sql`.

Default weights (only ratios matter): grocery 14, transit 14, emergencyCorridor
12, restaurant 10, school 10, gym 9, cafe 8, gasConvenience 6, bar 5, airport 5,
recreation 5, shopping 4, traffic 4. v2 rows keep working: the API reads a v2
row's Shopping from `premium_retail_score` and Recreation from
`trail_popularity_score`, and its `gasConvenience` is null. Legacy API keys
(`premiumRetail`, `trailPopularity`, `road`, `gasStation`, `convenienceStore`) are
aliases.

## A7. Cohorts, areas and known weaknesses

- Normalization is per `metro_area` cohort of geohash6 cells (about 0.6 x 0.4 mi).
  Scores for a road-bounded area (`GET /v1/area`) are not normalized separately:
  they are the area-weighted average of the overlapping cells' latest scores, so
  small areas inherit similar scores (`precision=point`, A8, scores sample points
  inside the polygon instead).
- Scores are relative within a metro area, so no place scores 100 on everything
  (factors pull in opposite directions: dense places have the best transit and
  cafes and also the most traffic and siren noise).
- **Known weakness (fixed in v3).** Min-max normalization is skewed by outlier
  distances: a few very far nearest-feature distances stretch the range, which
  compresses everyone else and lets remote cells with little around them score
  high on restaurant and bar. Part B replaces it with absolute time curves.
- Other limits: school ratings are district-level, airport time is straight-line
  until routing exists, and quality of gyms, restaurants and groceries is not
  measured.

## A8. On-demand point scoring (`precision=point`, experimental)

`GET /v1/score` and `GET /v1/area` accept `precision=point` (default `grid`, unchanged).
A point is scored at its exact coordinates instead of reusing the stored score of the
0.24 sq mi cell it falls in, with **no per-cell storage**. Code: `scoring/point.py`
(raw features at a point), `scoring/scales.py` (normalization), `api/point_score.py`
(DB wiring).

- **Raw features.** The same feature dict the ingestion jobs write for a cell, built from
  one PostGIS statement against `places.geom` (GiST box counts and KNN, distances by
  `ST_DistanceSphere`). Grocery, gym, cafe, restaurant, bar, gas, convenience, transit
  and school come live; the airport time is computed (it is straight-line in production).
- **Anchoring.** `places` only holds named OSM elements and parks as one centre point,
  while `feature_store` was computed from every element and from park footprints. So for
  most categories the live value is measured at the point and at the cell's stored
  centroid and the stored cell value is shifted by the difference (nearest distances are
  clipped to the point-to-centroid distance). At a cell's centroid this reproduces the
  stored value. Schools need no anchoring (the 3x3 bucket rule of the ingestion is
  replicated).
- **Cell-only inputs.** Traffic (`congestion_proxy_raw`), the Noise Corridor base signal
  and street orientation, trail features, the school district rating, shopping variety
  and the largest nearby park are not queryable live (`road_segments` is empty), so they
  come from the containing cell. The gas / convenience adjacency penalty inside Noise
  Corridor is live.
- **Normalization.** Each factor is scaled with the metro's p2 / p98 (v2.1) raw bounds,
  computed with the engine's own functions (`compute_scales`), so scoring the stored raw
  row of a cell reproduces its stored score exactly. Read from `score_scales`
  (migration 0013, written by `scoring/run.py`) or, until that exists, computed once per
  metro per Lambda instance from `feature_store`.
- **Areas.** The mean of up to five points inside the polygon (the point nearest its
  bounding-box centre plus farthest-point picks on a 5 x 5 lattice), equal weights.
- Validation numbers: `scripts/validate_point_scoring.py`.

## A9. Routing precompute (inputs for time-based scoring)

The Wave 4 precompute (`ingestion/routing/`, migration 0022, see ARCHITECTURE section 6) stores
network minutes to the nearest, 2nd and 3rd nearest place of every category per cell (walk for
cells at or above 10,000 people / sq mi, drive below), drive minutes to airports and rail
stations, and rail ride times between stations. **No score reads them yet**: v2 / v2.1 still use
straight-line distances, and the v3 time curves (Part B 1.2) will take these minutes as input.
Optimizer and triangulate already use them. Assumptions to carry into v3: walk 3 mph;
drive free-flow x 0.8; amenity search caps walk 30 min / drive 45 min (beyond = "not reachable",
which a time curve should score as zero); train times are weekday AM peak and include the wait.

---

## A10. v2.2 (`v2.2-density`): routed density per area

Why: v2.1 scales every factor within its sub-region and mostly by distance, so a hamlet
with one bar 1,500 ft away scored 100 on bars (Lloyd, NY: the best in the Hudson Valley
cohort), and 23-36 % of all cells scored 90+ on each amenity. v2.2 scores each
road-bounded area once, on one absolute scale for the whole region, from routed travel
times. Owner decisions 2026-10-05.

| Factor | Score |
| --- | --- |
| Restaurants, cafes, bars, shopping | 100 % density: places per sq mi over the area plus its walkable neighbours (weight 1 within 5 min, linear to 0 at 20), on a log scale (full marks at 60 restaurants, 20 cafes, 15 bars or 60 shops per sq mi). Drive-mode areas also score for the best dense cluster by car: full within 5 min, linear to 0 at 15, worth at most 80 %. |
| Groceries, gym, gas & convenience | 70 % proximity (minutes to the nearest; walk curve everywhere, a drive curve worth at most 80 % in drive-mode areas), 30 % density |
| Transit | minutes to a train station (walk 10 -> 30 min; drive-mode areas also park-and-ride by car 5 -> 20 min at 80 %); a bus stop at most half. No density. |
| Schools | 20 % proximity (routed) + 80 % district rating (statewide percentile) |
| Airport | drive minutes to JFK / LGA / EWR: full within 20, 0 at 75 |
| Traffic, noise corridor, recreation | the v2.1 signals, scaled once over the whole region (2nd-98th percentile) |

Densities, tallies and minutes are internal inputs and are never shown to users; only the
0-100 factor scores leave `scoring/density.py`. Units are miles, sq mi, mph and minutes.

Pipeline (offline, about 20 minutes on a laptop; nothing heavy runs in CI or the API):

    python -m ingestion.routing.pbf                       # Geofabrik NY/NJ/CT -> walk + drive networks
    python -m ingestion.routing.reach --sync-places       # production places -> build/reach/reach.npz
    python -m scoring.area_run [--preview DIR] [--write]  # scores, area file, DB rows

`--write` stores one `area_scores` row per area (migration 0023) and gives every grid cell
its area's scores in `scores`, so the map, hover, card, score file and `/v1/score` agree.
`GET /v1/area` serves the stored row for a density version. The weekly job does not
recompute v2.2 (`scoring.run` skips it); re-run the pipeline after a data refresh.
Calibration against reference places: `scripts/calibrate_density.py`.

# Part B: v3 framework (planned, `v3-timeaccess`)

> **Status: target design, framework v1.4 (2026-10-04).** The model served today is
> `v2-handtuned`; v2.1 is built. Part A section A6 and the mapping table in
> section 11 below show which pieces already exist. Items marked **OPEN** still need
> an owner decision. Changes and owner decisions are listed in section 12.

## 1. Scoring Philosophy

Humans evaluate places partly through **time-to-access** rather than raw distance. Lower
travel times should receive disproportionately higher scores because convenience has
diminishing value as travel time increases.

The tables in this document use a **0–10 scale** for readability:

- **10 = Excellent**
- **8–9 = Very good**
- **6–7 = Good**
- **4–5 = Average**
- **2–3 = Poor**
- **0–1 = Very poor / effectively unavailable**

The product stores and shows every score **out of 100** (table value × 10), for factors and
for the overall score. See section 6.

### 1.1 Travel mode follows population density

How people reach things depends on where they live: in a dense city people walk and take
the train; in a suburb they drive. Each grid cell gets a **density class** from its
residential population density (2020 Census, people per square mile, area-weighted from
block groups), and the class sets the default mode:

| Density class | People / sq mi | Default mode                                        | Examples (approx. density) |
| ------------- | -------------: | --------------------------------------------------- | -------------------------- |
| Walkable      | 10,000+        | walk, and transit for anything beyond a 15-min walk | Manhattan, Brooklyn, Hoboken, Jersey City, Yonkers |
| Car           | under 10,000   | drive (walk only when it is faster, which is rare)  | Montclair, White Plains, Long Island, Westchester, NJ suburbs |

Rules:

- The factor score uses the **better** of the allowed modes for that class.
- Drive times include a parking / access overhead: +5 min in Walkable cells, +2 min in Car cells.
- Transit proximity is always a walking time to a stop. In Car cells a commuter-rail
  station within a 10-min drive also counts (park-and-ride).
- Airport access is always drive, with transit shown separately (4.1).
- The 10,000 threshold is the owner's decision (2026-10-04); it can be revisited after the
  first run against known places.

Until routing is precomputed (section 10 below), minutes are **estimated**: straight-line
distance × 1.3 (street circuity) ÷ mode speed (walk 3 mph; drive 20 mph in Walkable
cells, 30 mph in Car cells). Estimates are labelled "approx." wherever shown.

### 1.2 Proximity curves — each factor has its own time range

Every factor scores 10 up to its *full-marks* time, then falls linearly to 0 at its
*zero* time. The range reflects how far people will reasonably go for that thing, in the
cell's travel mode (1.1):

| Factor              | Walkable cells (walk / transit) | Car cells (drive)        |
| ------------------- | ------------------------------- | ------------------------ |
| Groceries           | 10 ≤ 5 min → 0 at 25 min        | 10 ≤ 5 min → 0 at 20 min |
| Restaurants, cafes, bars | 10 ≤ 5 min → 0 at 20 min   | 10 ≤ 5 min → 0 at 20 min |
| Gym                 | 10 ≤ 7 min → 0 at 30 min        | 10 ≤ 7 min → 0 at 25 min |
| Recreation (parks, trails) | 10 ≤ 5 min → 0 at 20 min | 10 ≤ 5 min → 0 at 20 min |
| Shopping            | 10 ≤ 10 min → 0 at 40 min       | 10 ≤ 10 min → 0 at 30 min |
| Gas & Convenience   | 10 ≤ 5 min → 0 at 20 min        | 10 ≤ 3 min → 0 at 15 min |
| Public transit (walk to stop) | 10 ≤ 5 min → 0 at 20 min | rail station by car: 10 ≤ 5 min → 0 at 20 min |
| Schools             | 10 ≤ 10 min → 0 at 30 min       | 10 ≤ 10 min → 0 at 25 min |
| Airport (drive)     | 10 ≤ 20 min → 0 at 75 min       | same                     |

These are starting values to check against known places after the first run.

For categories with several options (restaurants, cafes, bars, groceries, gyms, gas /
convenience) the input is the time to the **k-th nearest** option (k = 3; k = 2 for
groceries), so one outlier does not define the score.

---

## 2. Factor Weights

**Principle (owner, 2026-10-04): factors people use more often weigh more.** Each default
weight combines how often a typical household uses the thing with how much each use costs
in time, with diminishing returns (a weekly errand is not worth 7× a daily one — weight
grows with roughly the square root of frequency). Exposure factors that affect you every
hour you are home (noise) are treated as the most frequent of all. Rare-but-costly trips
(airport) get a modest weight.

Default weights (accepted by the owner 2026-10-04; only their ratios matter, see 2.1).
Every factor is a user-facing pill — there are no hidden "underlying" factors:

| Category        | Pill (icon)                 | Typical use                          | Weight |
| --------------- | --------------------------- | ------------------------------------ | -----: |
| Daily Amenities | Groceries (cart)            | 2–3 trips / week                     | **14** |
| Getting Around  | Public transit (train)      | commute, up to 10 trips / week       | **14** |
| Neighborhood    | Noise Corridor (siren)      | continuous exposure, incl. sleep     | **12** |
| Daily Amenities | Restaurants (fork & knife)  | 2–3 meals out / week                 | **10** |
| Neighborhood    | Schools (graduation cap)    | daily for families (off for others)  | **10** |
| Daily Amenities | Gym (dumbbell)              | ~3 visits / week for members         |  **9** |
| Daily Amenities | Cafes (cup)                 | several visits / week                |  **8** |
| Getting Around  | Gas & Convenience (pump)    | ~1–2 stops / week                    |  **6** |
| Daily Amenities | Bars (glass)                | ~1 visit / week                      |  **5** |
| Getting Around  | Airport (plane)             | a few trips / year, each long        |  **5** |
| Neighborhood    | Recreation (tree)           | parks and trails, several times / week for many | **5** |
| Daily Amenities | Shopping (bag)              | occasional                           |  **4** |
| Getting Around  | Traffic (car)               | every drive                          |  **4** |

Restaurants, cafes and bars stay **separate pills** (owner, 2026-10-04); they share the
same scoring method (3.2) but have their own weights.

**Mode-aware adjustment (accepted):** in Car cells (1.1) transit matters less day to day
and fuel more, so transit × 0.6 and Gas & Convenience × 1.5 there. The presets (Daily
errands, Family, Commuter, Quiet) and the importance sliders scale these defaults further,
and the optimizer / chat can use a user's own trip frequencies instead.

There is **no reserved weight**: new factors are simply added with their own weight and
the 2.1 normalization keeps every score out of 100.

### 2.1 The overall score is normalized to the selected filters

The total always depends on which filters the user selects, so it is **normalized by the
weight of the factors actually used** and always comes out of 100:

**Overall (0–100) = 10 × Σ(score × weight) ÷ Σ(weight of selected factors that have a score)**

- With every filter on, this is the default score; with only groceries and transit on, it
  is the weighted average of those two — still out of 100.
- Importance sliders multiply a factor's weight before normalizing.
- A factor with no data for a place (for example a school with no rating) is left out of
  both sums, never scored 0.
- Adding a new factor later never caps or shifts the scale: it joins both sums.

---

## 3. Daily Amenities

**Quality is a placeholder for now.** Several factors below have a *Quality* part (gym
quality, dining and grocery quality). There is no quality data yet (section 10). Until a
source exists, a factor uses only the parts it has, re-weighted to 100%: for example the gym
score is 100% proximity until quality data lands, at which point it becomes 70 / 30.

### 3.1 Gym — Weight: 9

**Gym Score = 70% Proximity + 30% Quality** (quality pending → 100% proximity today)

- **Proximity:** 1.2 curve, k-th nearest gym, mode by density class.
- **Quality (placeholder):**

| Quality           | Score |
| ----------------- | ----: |
| Excellent         |    10 |
| Very good         |     8 |
| Good              |     6 |
| Average           |     4 |
| Poor              |     2 |
| No meaningful gym |     0 |

### 3.2 Restaurants, Cafes, Bars — Weights: 10 / 8 / 5

Three separate pills and factors that share one method. Each captures **convenience**,
**density within the area**, and later **quality**.

**Dining Score = 50% Proximity + 30% Density + 20% Quality**
(quality pending → 62.5% proximity + 37.5% density today)

- **Proximity:** 1.2 curve, k-th nearest.
- **Density (0–10):** how many places of that type are *within the area* — the
  road-bounded neighborhood polygon plus a 10-minute walk around it — per square mile,
  scored against the metro distribution (top 10% of areas = 10). A block with 40 cafes
  beats a block with one cafe next door and nothing else.
- **Quality (placeholder):**

| Score | Description                                             |
| ----: | ------------------------------------------------------- |
|    10 | Large, diverse, high-quality cluster immediately nearby |
|     8 | Strong selection and good variety                       |
|     6 | Decent selection                                        |
|     4 | Limited options                                         |
|     2 | Very few options                                        |
|     0 | Essentially no meaningful options                       |

### 3.3 Groceries — Weight: 14

**Grocery Score = 60% Proximity + 20% Variety + 20% Quality**
(quality pending → 75% proximity + 25% variety today)

- **Proximity:** 1.2 curve, k-th nearest (k = 2).
- **Variety:** number of distinct full-service grocers within 15 min and format mix
  (supermarket, specialty, warehouse).
- **Quality:** placeholder.

### 3.4 Recreation — Weight: 5 (tree icon)

Parks and trails together (replaces the hidden "running-trail popularity" signal).

**Recreation Score = 50% Park proximity + 25% Park size / quality + 25% Trail access**

- **Park proximity:** 1.2 curve to the nearest park, playground or nature area (OSM
  `leisure=park|playground|nature_reserve`, `landuse=recreation_ground`).
- **Park size / quality:** largest park within a 10-min walk (a pocket park is not Prospect
  Park); quality is a placeholder.
- **Trail access:** distance to a trail and its popularity (existing trail data).

### 3.5 Shopping — Weight: 4 (bag icon)

Replaces the hidden "premium retail" signal with a visible, broader factor.

**Shopping Score = 60% Proximity + 40% Variety**

- **Proximity:** 1.2 curve to the k-th nearest general retail destination (department
  stores, malls, clothing, home goods, pharmacies; OSM `shop=*` major classes).
- **Variety:** distinct retail types within 15 min, with a bonus for anchor stores
  (Target, Whole Foods and similar, as today's premium retail signal).

---

## 4. Getting Around

### 4.1 Airport Access — Weight: 5

**Airport Score = 70% Travel Time + 30% Reliability / Convenience**

| Drive time to a major airport | Score |
| ----------------------------- | ----: |
| 0–20 min                      |    10 |
| 30 min                        |     9 |
| 40 min                        |     7 |
| 50 min                        |     5 |
| 60 min                        |     3 |
| 75+ min                       |     0 |

(Interpolated between points.) **Reliability / Convenience:** direct rail to a terminal,
number of airports within 60 min, transit access to a terminal. Travel-time variability
needs traffic data and is a placeholder.

### 4.2 Public Transportation — Weight: 14

**Transit Score = 60% Proximity + 40% Service**

- **Proximity:** walking minutes to the nearest stop; rail (subway, commuter rail, PATH,
  light rail) within a 15-min walk scores at least 8. Car cells also credit a
  commuter-rail station within a 10-min drive.
- **Service:** distinct routes / lines within a 10-min walk and rail-versus-bus mix;
  peak frequency once schedules are used.

### 4.3 Gas & Convenience — Weight: 6

**Decided 2026-10-04:** gas stations and convenience stores are **one positive category**:
having fuel and a quick-stop store nearby is a convenience. Living *right next to* one is
still a negative, scored under the Noise Corridor (5.2). The two use the same locations at
different distances, so they do not conflict.

- **Proximity:** 1.2 curve for k-th nearest (k = 2), mode by density class (Walkable:
  walk; Car: drive).
- **Availability bonus** (options within 10 minutes): 0–1 +0, 2–3 +0.5, 4 or more +1.
  Cap at 10.

### 4.4 Traffic — Weight: 4 (car icon)

Renamed from "Road conditions", which was vague. It measures how busy the roads around a
place are (a congestion proxy from road class and density); fewer busy roads score higher.
Once drive times are precomputed with routing, congestion shows up in travel times directly,
and this factor can be folded into those times and retired.

---

## 5. Neighborhood

### 5.1 Schools — Weight: 10

**School Score = 20% Proximity + 80% Quality** (decided; matches the shipped product)

- **Proximity:** 1.2 curve, mode by density class.
- **Quality:** district proficiency today (EDFacts via the Urban Institute Education Data
  Portal), converted to 0–10 by per-state percentile; school-level ratings later.
- No rating → **no school score** (left out of the overall, never 0).

If schools are not relevant, the user turns the filter off; 2.1 handles the rest.

### 5.2 Noise Corridor — Weight: 12

Noise is an **inverse factor**: closer to noise sources is worse.

**Noise is about which side of the building you are on (owner, 2026-10-04).** Sirens and
arterial traffic mainly affect buildings that *front* the main road; homes on the inside of
the block, facing away from the street, are shielded by the buildings in front of them. So
noise is scored by **position relative to the road**, not by plain distance:

| Position relative to a major road / emergency route | Share of the source's penalty |
| --------------------------------------------------- | ----------------------------: |
| Frontage: within ~100 ft of the road (the first row of buildings) | 100% |
| Behind the first row: 100–300 ft                    | 35%                           |
| Block interior: 300–600 ft                          | 10%                           |
| Beyond 600 ft                                       | 0%                            |

Highways and railroads carry farther (open sound paths, constant volume), so they use a
wider fade: 100% to 500 ft, 50% to 1,000 ft, 0 beyond 1,500 ft.

How this applies at each level the product scores:

- **An address** (search or click): the exact distance from the point to the nearest road
  centerline, so a building on the avenue and one around the corner on a side street get
  different noise scores even inside the same block.
- **A neighborhood area:** the share of the area's land in each band (most of a block's
  land is interior, so a quiet residential block is not punished for having an avenue on
  one edge).
- **A map grid square:** the same share-of-land rule.

This needs the major-road line geometry stored (today only per-cell summaries are kept);
see section 10.

Inputs:

| Source                                         | Data                                             |
| ---------------------------------------------- | ------------------------------------------------ |
| Highways, arterials, railroads                 | OSM road / rail classes and geometry             |
| Emergency routes (fire, hospital, police)      | OSM facilities + the major roads near them (in use) |
| **Gas stations and convenience stores next door** | OSM locations (in use). Loitering / undesirable clientele and fuel fumes. Full penalty within 300 ft, fading to none at 800 ft. |
| Airport flight paths                           | BTS National Transportation Noise Map (free; to add) |
| Nightlife districts                            | bar density (a trade-off with Bars as an amenity) |
| Construction, nighttime noise                  | NYC DOB permits, 311 noise complaints (NYC only; later) |

| Noise exposure             | Score |
| -------------------------- | ----: |
| Very quiet                 |    10 |
| Low                        |     8 |
| Moderate                   |     6 |
| Noticeable                 |     4 |
| High                       |     2 |
| Severe / directly adjacent |     0 |

---

## 6. Composite Scoring Method

Each factor produces a 0–10 score internally, stored and shown as **0–100**. The overall
score is the normalized weighted average in 2.1, also **out of 100**.

Example (default weights, all filters on): groceries 80, transit 95, noise 50,
restaurants 90, schools 75, gym 85, cafes 92, gas & convenience 70, bars 88, airport 60 →
(80×14 + 95×14 + 50×12 + 90×10 + 75×10 + 85×9 + 92×8 + 70×6 + 88×5 + 60×5) ÷ 93 = **79**.

With only groceries and transit selected: (80×14 + 95×14) ÷ 28 = **88**.

---

## 7. Recommended Interpretation

| Overall (out of 100) | Label         |
| -------------------: | ------------- |
|              90–100  | Exceptional   |
|               80–89  | Excellent     |
|               70–79  | Very Good     |
|               60–69  | Good          |
|               50–59  | Average       |
|               40–49  | Below Average |
|                0–39  | Poor          |

---

## 8. Important Modeling Principle

Do **not** make every factor purely distance-based. Use **Proximity + Density / Variety +
Quality + Reliability** where appropriate.

A gym 3 minutes away but mediocre may be less valuable than an excellent gym 10 minutes
away. A neighborhood with 20 restaurants nearby is not necessarily better than one with 8
excellent restaurants and strong variety. The goal is **real-world convenience and
quality**, not geographic distance.

Scores are **absolute** (minutes → score), not ranked against the metro. The shipped v2
model min-max normalizes against the whole metro, which lets outliers distort scores (a
restaurant 4 miles away still scoring 88); v3 fixes that. Density (3.2) is the one input
scored against the metro distribution, because "a lot of cafes" has no absolute meaning.

---

## 9. Future Factors to Add

New factors to add (not already scored above), each with its own weight:

- Walkability
- Parks / green space
- Safety
- Commute to work (per user, via triangulation)
- Downtown / main-street access
- Neighborhood character
- Housing quality and affordability
- Property taxes
- Highway access
- Future development, appreciation / resale potential
- Healthcare access
- Social / nightlife access
- Seasonal considerations

---

## 10. Data Plan

| Need                                   | Today                          | Plan                                                    |
| -------------------------------------- | ------------------------------ | ------------------------------------------------------- |
| Walk / drive **times**                 | straight-line estimate         | **Precomputed with Valhalla** (decided): batch run on a laptop (Docker) or a short-lived AWS spot instance; minutes stored per cell. Live triangulation from arbitrary addresses uses a hosted routing free tier. |
| Transit times                          | nearest-stop distance          | Valhalla with GTFS; needs the NJ Transit feed           |
| Gym / dining / grocery **quality**     | none (placeholder)             | ratings source, later                                   |
| Dining density within the area         | counts within 500 m            | counts within the road-bounded area + 10-min walk       |
| School-level quality                   | district proficiency           | state report cards, later                               |
| Noise                                  | per-cell road / facility proxy | store major-road geometry; frontage bands (5.2); gas / convenience adjacency; BTS noise map later |
| Population density                     | none                           | 2020 Census block groups (free), sets the travel mode   |
| Airport reliability                    | none (placeholder)             | traffic data, later                                     |

---

## 11. Mapping To The Current Implementation

| Framework (v3) | `v2-handtuned` (live) | `v2.1-handtuned` (built) |
| --- | --- | --- |
| Absolute time curves, mode by density | min-max normalized distance + count blend | same |
| Overall normalized to selected filters, out of 100 | same | same |
| Gas & Convenience one positive factor | two separate negative factors | one positive factor |
| Gas / convenience adjacency inside Noise | not in Noise | in Noise (300 ft to 800 ft fade) |
| Recreation and Shopping as visible pills | hidden underlying signals | visible pills |
| Transit proximity + service | proximity and stop count | same |
| Dining proximity + density in area | proximity + count within 500 m | same |
| School 20 / 80 | 20 / 80 | same |
| Weights (section 2) | older hand-tuned weights (A3) | the section 2 weights |
| Quality parts | none (placeholders in v3 too) | none |

------------------------------------------- | ----------------------------------------------------- |
| Absolute time curves, mode by density       | min-max normalized distance + count blend             |
| Overall normalized to selected filters, /100 | same normalization, /100 (already)                   |
| Gas & Convenience one positive factor       | two separate negative factors                         |
| Gas / convenience adjacency inside Noise    | not in Noise                                          |
| Transit proximity + service                 | proximity and stop count                              |
| Dining proximity + density in area          | proximity + count within 500 m                        |
| School 20 / 80                              | 20 / 80 (same)                                        |
| Quality parts                               | none (placeholders in v3 too)                         |

---

## 12. Changes

**v1.1 (review of v1.0):** weights summed to 123% (reserve now 17%); the overall formula
could never exceed 6/10 with an unallocated reserve (now normalized by active weight);
Public transportation had a weight but no section (4.2 added); section 3.2 duplicated
Groceries; future factors repeated existing ones; proximity tables were hard steps (now
interpolated, k-th nearest); labels harmonized; measurable inputs named.

**v1.2 (owner decisions, 2026-10-04):**

1. Overall score normalized to the selected filters and shown out of 100 (2.1, 6).
2. Gas stations and convenience stores merged into one positive *Gas & Convenience*
   factor; both remain a negative noise source when directly adjacent (4.3, 5.2).
3. Default travel mode set by population density: urban walk + transit, suburban drive (1.1).
4. Quality components are placeholders; factors use their available parts until data exists.
5. Schools 20 / 80 confirmed.
6. Routing: precompute with Valhalla (option a).
7. Dining factors include density of places within the area (3.2).

**v1.3 (owner decisions, 2026-10-04):**

1. No reserved weight: new factors are added and normalized (2, 2.1).
2. Restaurants, cafes and bars stay separate pills with their own weights (2, 3.2).
3. Weights follow frequency of use with diminishing returns; recommended defaults in 2.
4. Noise is scored by position relative to the road (frontage vs block interior) (5.2).
5. Travel mode: car below 10,000 people / sq mi, walk + transit at or above (1.1).

**v1.4 (owner decisions, 2026-10-04):**

1. Weights and the mode-aware adjustment accepted.
2. Every factor is a pill: Recreation (tree: parks + trails) and Shopping (bag) replace the
   hidden underlying signals (3.4, 3.5).
3. Icons: airport plane, noise corridor siren; "Bars & Pubs" becomes "Bars"; "Road
   conditions" renamed "Traffic" (4.4).
4. Proximity curves are per factor and per travel mode (1.2), replacing one shared curve.
5. Neighborhood polygons are capped at 0.8 sq mi.

