const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";

export interface GeohashBounds {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
}

/**
 * The rectangle a geohash covers. Bits alternate longitude, latitude, starting
 * with longitude; each bit halves the remaining interval. Returns `null` for
 * an empty string or any character outside the geohash alphabet.
 */
export function decodeBounds(hash: string): GeohashBounds | null {
  if (hash.length === 0) return null;

  let minLat = -90;
  let maxLat = 90;
  let minLon = -180;
  let maxLon = 180;
  let isLon = true;

  for (const char of hash.toLowerCase()) {
    const value = BASE32.indexOf(char);
    if (value === -1) return null;
    for (let bit = 4; bit >= 0; bit--) {
      const set = (value >> bit) & 1;
      if (isLon) {
        const mid = (minLon + maxLon) / 2;
        if (set) minLon = mid;
        else maxLon = mid;
      } else {
        const mid = (minLat + maxLat) / 2;
        if (set) minLat = mid;
        else maxLat = mid;
      }
      isLon = !isLon;
    }
  }
  return { minLat, maxLat, minLon, maxLon };
}
