"use client";

import { useEffect, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, ReachMode } from "@/lib/api/types";

export type MainReach =
  | { status: "off" }
  | { status: "loading" }
  | { status: "ready"; geometry: AreaGeometry | null; estimate: boolean }
  | { status: "error" };

/**
 * The searched place's travel area (`GET /isochrone`) for the travel set in the search box,
 * while `visible`. Follows each new place, mode and minutes; aborts what it no longer needs.
 */
export function useMainReach(
  client: Pick<ApiClient, "getReach">,
  coordinates: { lat: number; lon: number } | null,
  mode: ReachMode,
  minutes: number,
  visible: boolean,
): MainReach {
  const [reach, setReach] = useState<MainReach>({ status: "off" });
  const lat = coordinates?.lat;
  const lon = coordinates?.lon;

  useEffect(() => {
    if (!visible || lat === undefined || lon === undefined) {
      setReach({ status: "off" });
      return;
    }
    const controller = new AbortController();
    // The previous area stays drawn until the new one arrives, so the map does not flash.
    setReach((current) => (current.status === "ready" ? current : { status: "loading" }));
    client
      .getReach(lat, lon, mode, minutes, { signal: controller.signal })
      .then((result) => {
        setReach({
          status: "ready",
          geometry: result.geometry,
          estimate: result.method === "estimate",
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setReach({ status: "error" });
      });
    return () => controller.abort();
  }, [visible, lat, lon, mode, minutes, client]);

  return reach;
}
