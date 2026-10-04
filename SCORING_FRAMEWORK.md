# Scoring Framework (v1.2 — 2026-10-04)

> **Status:** target design for the next scoring model (`v3-timeaccess`). The model
> served today is `v2-handtuned` (distance-based, min-max normalized). Section 11 maps
> this framework to what exists. Items marked **OPEN** still need an owner decision.
> Changes are listed in section 12.

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

Until routing is precomputed (section 10), minutes are **estimated**: straight-line
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

# 2. Factor Weights

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

# 3. Daily Amenities

**Quality is a placeholder for now.** Several factors below have a *Quality* part (gym
quality, dining and grocery quality). There is no quality data yet (section 10). Until a
source exists, a factor uses only the parts it has, re-weighted to 100%: for example the gym
score is 100% proximity until quality data lands, at which point it becomes 70 / 30.

## 3.1 Gym — Weight: 9

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

## 3.2 Restaurants, Cafes, Bars — Weights: 10 / 8 / 5

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

## 3.3 Groceries — Weight: 14

**Grocery Score = 60% Proximity + 20% Variety + 20% Quality**
(quality pending → 75% proximity + 25% variety today)

- **Proximity:** 1.2 curve, k-th nearest (k = 2).
- **Variety:** number of distinct full-service grocers within 15 min and format mix
  (supermarket, specialty, warehouse).
- **Quality:** placeholder.

## 3.4 Recreation — Weight: 5 (tree icon)

Parks and trails together (replaces the hidden "running-trail popularity" signal).

**Recreation Score = 50% Park proximity + 25% Park size / quality + 25% Trail access**

- **Park proximity:** 1.2 curve to the nearest park, playground or nature area (OSM
  `leisure=park|playground|nature_reserve`, `landuse=recreation_ground`).
- **Park size / quality:** largest park within a 10-min walk (a pocket park is not Prospect
  Park); quality is a placeholder.
- **Trail access:** distance to a trail and its popularity (existing trail data).

## 3.5 Shopping — Weight: 4 (bag icon)

Replaces the hidden "premium retail" signal with a visible, broader factor.

**Shopping Score = 60% Proximity + 40% Variety**

- **Proximity:** 1.2 curve to the k-th nearest general retail destination (department
  stores, malls, clothing, home goods, pharmacies; OSM `shop=*` major classes).
- **Variety:** distinct retail types within 15 min, with a bonus for anchor stores
  (Target, Whole Foods and similar, as today's premium retail signal).

---

# 4. Getting Around

## 4.1 Airport Access — Weight: 5

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

## 4.2 Public Transportation — Weight: 14

**Transit Score = 60% Proximity + 40% Service**

- **Proximity:** walking minutes to the nearest stop; rail (subway, commuter rail, PATH,
  light rail) within a 15-min walk scores at least 8. Car cells also credit a
  commuter-rail station within a 10-min drive.
- **Service:** distinct routes / lines within a 10-min walk and rail-versus-bus mix;
  peak frequency once schedules are used.

## 4.3 Gas & Convenience — Weight: 6

**Decided 2026-10-04:** gas stations and convenience stores are **one positive category**:
having fuel and a quick-stop store nearby is a convenience. Living *right next to* one is
still a negative, scored under the Noise Corridor (5.2). The two use the same locations at
different distances, so they do not conflict.

- **Proximity:** 1.2 curve for k-th nearest (k = 2), mode by density class (Walkable:
  walk; Car: drive).
- **Availability bonus** (options within 10 minutes): 0–1 +0, 2–3 +0.5, 4 or more +1.
  Cap at 10.

## 4.4 Traffic — Weight: 4 (car icon)

Renamed from "Road conditions", which was vague. It measures how busy the roads around a
place are (a congestion proxy from road class and density); fewer busy roads score higher.
Once drive times are precomputed with routing, congestion shows up in travel times directly,
and this factor can be folded into those times and retired.

---

# 5. Neighborhood

## 5.1 Schools — Weight: 10

**School Score = 20% Proximity + 80% Quality** (decided; matches the shipped product)

- **Proximity:** 1.2 curve, mode by density class.
- **Quality:** district proficiency today (EDFacts via the Urban Institute Education Data
  Portal), converted to 0–10 by per-state percentile; school-level ratings later.
- No rating → **no school score** (left out of the overall, never 0).

If schools are not relevant, the user turns the filter off; 2.1 handles the rest.

## 5.2 Noise Corridor — Weight: 12

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

# 6. Composite Scoring Method

Each factor produces a 0–10 score internally, stored and shown as **0–100**. The overall
score is the normalized weighted average in 2.1, also **out of 100**.

Example (default weights, all filters on): groceries 80, transit 95, noise 50,
restaurants 90, schools 75, gym 85, cafes 92, gas & convenience 70, bars 88, airport 60 →
(80×14 + 95×14 + 50×12 + 90×10 + 75×10 + 85×9 + 92×8 + 70×6 + 88×5 + 60×5) ÷ 93 = **79**.

With only groceries and transit selected: (80×14 + 95×14) ÷ 28 = **88**.

---

# 7. Recommended Interpretation

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

# 8. Important Modeling Principle

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

# 9. Future Factors to Add

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

# 10. Data Plan

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

# 11. Mapping To The Current Implementation

| Framework                                   | Shipped (`v2-handtuned`)                              |
| ------------------------------------------- | ----------------------------------------------------- |
| Absolute time curves, mode by density       | min-max normalized distance + count blend             |
| Overall normalized to selected filters, /100 | same normalization, /100 (already)                   |
| Gas & Convenience one positive factor       | two separate negative factors                         |
| Gas / convenience adjacency inside Noise    | not in Noise                                          |
| Transit proximity + service                 | proximity and stop count                              |
| Dining proximity + density in area          | proximity + count within 500 m                        |
| School 20 / 80                              | 20 / 80 (same)                                        |
| Quality parts                               | none (placeholders in v3 too)                         |

---

# 12. Changes

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
