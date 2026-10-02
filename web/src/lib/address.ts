import { APP_PATH } from "@/lib/site";

export const ADDRESS_MIN_LENGTH = 3;
export const ADDRESS_MAX_LENGTH = 200;
export const ADDRESS_PARAM = "address";
export const LAT_PARAM = "lat";
export const LON_PARAM = "lon";

export type AddressValidation =
  | { ok: true; value: string }
  | { ok: false; message: string };

export function validateAddress(raw: string): AddressValidation {
  const value = raw.trim().replace(/\s+/g, " ");

  if (value.length === 0) {
    return { ok: false, message: "Enter an address to score." };
  }
  if (value.length < ADDRESS_MIN_LENGTH) {
    return {
      ok: false,
      message: `Enter at least ${ADDRESS_MIN_LENGTH} characters, such as a street and city.`,
    };
  }
  if (value.length > ADDRESS_MAX_LENGTH) {
    return {
      ok: false,
      message: `Addresses can be at most ${ADDRESS_MAX_LENGTH} characters.`,
    };
  }
  return { ok: true, value };
}

export interface LatLon {
  lat: number;
  lon: number;
}

/** What to score: free text to geocode, or coordinates that skip geocoding. */
export type ScoreTarget =
  | { kind: "address"; address: string }
  | {
      kind: "coordinates";
      lat: number;
      lon: number;
      label: string;
      /**
       * `"cell"` pins the lookup to the grid square (a best-areas pick);
       * otherwise the secondary-road area around the point is tried first.
       */
      precision?: "cell";
    };

/** Display text for the target; the heading of the result card. */
export function targetLabel(target: ScoreTarget): string {
  return target.kind === "address" ? target.address : target.label;
}

export function targetKey(target: ScoreTarget): string {
  return target.kind === "address"
    ? `a:${target.address}`
    : `c:${target.lat},${target.lon}`;
}

function parseCoordinate(raw: string | null, limit: number): number | null {
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) && Math.abs(value) <= limit ? value : null;
}

export function parseLatLon(params: URLSearchParams): LatLon | null {
  const lat = parseCoordinate(params.get(LAT_PARAM), 90);
  const lon = parseCoordinate(params.get(LON_PARAM), 180);
  return lat === null || lon === null ? null : { lat, lon };
}

export function formatLatLon({ lat, lon }: LatLon): string {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

/**
 * Valid coordinates win over free text, so a shared suggestion link reloads
 * without geocoding; the address parameter then only supplies the label.
 */
export function resolveTarget(params: URLSearchParams): {
  target: ScoreTarget | null;
  error: string | null;
} {
  const rawAddress = params.get(ADDRESS_PARAM);
  const validation = rawAddress === null ? null : validateAddress(rawAddress);
  const point = parseLatLon(params);

  if (point) {
    const label = validation?.ok ? validation.value : formatLatLon(point);
    return { target: { kind: "coordinates", ...point, label }, error: null };
  }
  if (validation?.ok) {
    return { target: { kind: "address", address: validation.value }, error: null };
  }
  return { target: null, error: validation ? validation.message : null };
}

export function resultHref(address: string, point?: LatLon): string {
  const params = new URLSearchParams({ [ADDRESS_PARAM]: address });
  if (point) {
    params.set(LAT_PARAM, String(point.lat));
    params.set(LON_PARAM, String(point.lon));
  }
  return `${APP_PATH}?${params}`;
}
