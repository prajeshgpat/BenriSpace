"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { LatLon } from "@/lib/address";
import {
  GEOLOCATION_OPTIONS,
  describeGeolocationError,
  geolocationUnsupportedReason,
  roundPosition,
} from "@/lib/geolocation";

export type LocateState =
  | { status: "idle" }
  | { status: "locating" }
  | { status: "error"; message: string };

interface CurrentLocation {
  state: LocateState;
  /** Why the button cannot work in this browser, or null. */
  unsupported: string | null;
  /** The only place the browser is ever asked for a position. */
  locate: () => void;
}

/**
 * `onPosition` receives the rounded position and returns an error message to
 * show, or null once the place has been selected.
 */
export function useCurrentLocation(
  onPosition: (point: LatLon) => Promise<string | null>,
): CurrentLocation {
  const [state, setState] = useState<LocateState>({ status: "idle" });
  // Read on the client only, so server and first client render agree.
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const busy = useRef(false);
  const alive = useRef(true);
  const handler = useRef(onPosition);

  useEffect(() => {
    handler.current = onPosition;
  });
  useEffect(() => {
    alive.current = true;
    setUnsupported(geolocationUnsupportedReason());
    return () => {
      alive.current = false;
    };
  }, []);

  const finish = useCallback((next: LocateState) => {
    busy.current = false;
    if (alive.current) setState(next);
  }, []);

  const locate = useCallback(() => {
    if (busy.current) return;
    const reason = geolocationUnsupportedReason();
    if (reason) {
      setUnsupported(reason);
      return;
    }
    busy.current = true;
    setState({ status: "locating" });
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        handler
          .current(roundPosition({ lat: coords.latitude, lon: coords.longitude }))
          .then(
            (message) =>
              finish(message ? { status: "error", message } : { status: "idle" }),
            () =>
              finish({
                status: "error",
                message: describeGeolocationError(2),
              }),
          );
      },
      (error) =>
        finish({ status: "error", message: describeGeolocationError(error.code) }),
      GEOLOCATION_OPTIONS,
    );
  }, [finish]);

  return { state, unsupported, locate };
}
