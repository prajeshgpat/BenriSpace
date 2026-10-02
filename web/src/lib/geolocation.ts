import type { LatLon } from "@/lib/address";
import { METRO_BBOX } from "@/lib/map/viewport";

export const YOUR_LOCATION_LABEL = "Your location";

export const GEOLOCATION_OPTIONS: PositionOptions = {
  enableHighAccuracy: false,
  timeout: 10_000,
  maximumAge: 60_000,
};

export const OUTSIDE_COVERAGE_MESSAGE =
  "You're outside the area BenriSpace covers — the NYC metro. Type an address in the metro area instead.";

/** Cells are about a kilometre across; ~11 m is far more than a score can use. */
const COORDINATE_DECIMALS = 4;

export function roundPosition({ lat, lon }: LatLon): LatLon {
  const factor = 10 ** COORDINATE_DECIMALS;
  return {
    lat: Math.round(lat * factor) / factor,
    lon: Math.round(lon * factor) / factor,
  };
}

export function isInCoverage({ lat, lon }: LatLon): boolean {
  const [west, south, east, north] = METRO_BBOX;
  return lon >= west && lon <= east && lat >= south && lat <= north;
}

/** Why locating cannot work here, or null when it can. */
export function geolocationUnsupportedReason(): string | null {
  if (typeof window === "undefined") return null;
  if (!window.isSecureContext) {
    return "Your location is only available on a secure (https) connection. Type an address instead.";
  }
  if (!("geolocation" in navigator) || !navigator.geolocation) {
    return "This browser can't share your location. Type an address instead.";
  }
  return null;
}

export function describeGeolocationError(code: number): string {
  switch (code) {
    case 1:
      return "Location access is blocked for this site. Allow it in your browser's site settings and try again, or type an address instead.";
    case 3:
      return "Finding your location took too long. Try again, or type an address instead.";
    default:
      return "Your device couldn't work out where you are. Try again, or type an address instead.";
  }
}
