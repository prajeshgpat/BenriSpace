/** Users see feet and miles only; the API and database keep metres. */

export const METERS_PER_MILE = 1609.344;
export const FEET_PER_MILE = 5280;
export const FEET_PER_METER = FEET_PER_MILE / METERS_PER_MILE;

/** Below this many miles a distance is shown in feet. */
const FEET_THRESHOLD_MI = 0.1;
const FEET_STEP = 50;

export function toMiles(meters: number): number {
  return meters / METERS_PER_MILE;
}

export function toFeet(meters: number): number {
  return meters * FEET_PER_METER;
}

/** "450 ft" under 0.1 mi (nearest 50 ft), otherwise "0.4 mi". */
export function formatDistance(meters: number): string {
  const miles = toMiles(meters);
  if (miles < FEET_THRESHOLD_MI) {
    const feet = Math.round(toFeet(meters) / FEET_STEP) * FEET_STEP;
    return `${feet} ft`;
  }
  return `${miles.toFixed(1)} mi`;
}

/** Same as {@link formatDistance} for a distance already in miles. */
export function formatMiles(miles: number): string {
  return formatDistance(miles * METERS_PER_MILE);
}

const ACRES_PER_SQ_MI = 640;

/** "45 acres" below a tenth of a square mile, otherwise "0.35 sq mi". */
export function formatArea(sqMi: number): string {
  if (sqMi < 0.1) {
    const acres = Math.max(1, Math.round(sqMi * ACRES_PER_SQ_MI));
    return `${acres} ${acres === 1 ? "acre" : "acres"}`;
  }
  if (sqMi < 1) return `${sqMi.toFixed(2)} sq mi`;
  return `${sqMi.toFixed(sqMi < 10 ? 1 : 0)} sq mi`;
}
