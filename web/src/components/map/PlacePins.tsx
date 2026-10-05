"use client";

import { Marker, type Map as MaplibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { FACTOR_ICONS, FACTOR_PIN_COLORS } from "@/lib/factorIcons";
import {
  clusterLabel,
  clusterScreenPoints,
  factorCounts,
  pinLabel,
  type KeyedPin,
} from "@/lib/map/placePins";

import styles from "./PlacePins.module.css";

/** Closer than this on screen (or zoomed this far in) a cluster cannot be split by zooming. */
const MIN_SPREAD_PX = 12;
const MAX_ZOOM = 18;
const EXPAND_ZOOM = 17.5;
const LIST_LIMIT = 8;

interface PinGroup {
  key: string;
  members: KeyedPin[];
  lat: number;
  lon: number;
}

interface Entry {
  group: PinGroup;
  element: HTMLElement;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function groupPins(map: MaplibreMap, pins: readonly KeyedPin[]): PinGroup[] {
  const points = pins.map((pin) => {
    const { x, y } = map.project([pin.longitude, pin.latitude]);
    return { pin, x, y };
  });
  return clusterScreenPoints(points).map(({ members }) => {
    const group = members.map((member) => member.pin);
    const lat = group.reduce((sum, p) => sum + p.latitude, 0) / group.length;
    const lon = group.reduce((sum, p) => sum + p.longitude, 0) / group.length;
    return {
      key: group.length === 1 ? group[0].key : `cluster|${group.map((p) => p.key).join("~")}`,
      members: group,
      lat,
      lon,
    };
  });
}

function safeRemove(marker: Marker) {
  try {
    marker.remove();
  } catch {
    // The map was torn down first; nothing is left to clean.
  }
}

function Badge({ factor, size }: { factor: KeyedPin["factor"]; size: number }) {
  const Icon = FACTOR_ICONS[factor];
  return (
    <span className={styles.dot} style={{ background: FACTOR_PIN_COLORS[factor] }}>
      <Icon width={size} height={size} />
    </span>
  );
}

interface PinProps {
  group: PinGroup;
  open: boolean;
  onToggle: (key: string) => void;
  onZoom: (group: PinGroup) => void;
}

function SinglePin({ group, open, onToggle }: PinProps) {
  const pin = group.members[0];
  const label = pinLabel(pin);
  const Icon = FACTOR_ICONS[pin.factor];
  return (
    <button
      type="button"
      className={styles.single}
      style={{ background: FACTOR_PIN_COLORS[pin.factor] }}
      aria-label={label}
      data-open={open ? "true" : undefined}
      data-place-pin="single"
      onClick={(event) => {
        event.stopPropagation();
        onToggle(group.key);
      }}
    >
      <Icon width={14} height={14} />
      <span className={styles.tip} aria-hidden="true">
        {label}
      </span>
    </button>
  );
}

function ClusterPin({ group, open, onToggle, onZoom }: PinProps) {
  const label = clusterLabel(group.members);
  const top = factorCounts(group.members).slice(0, 3);
  return (
    <>
      <button
        type="button"
        className={styles.cluster}
        aria-label={label}
        aria-expanded={open}
        data-place-pin="cluster"
        onClick={(event) => {
          event.stopPropagation();
          onZoom(group);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) onToggle(group.key);
        }}
      >
        <span className={styles.count}>{group.members.length}</span>
        <span className={styles.dots} aria-hidden="true">
          {top.map(({ factor }) => (
            <Badge key={factor} factor={factor} size={8} />
          ))}
        </span>
        <span className={styles.tip} aria-hidden="true">
          {label}
        </span>
      </button>
      {open ? (
        <ul
          className={styles.list}
          aria-label={label}
          onClick={(event) => event.stopPropagation()}
        >
          {group.members.slice(0, LIST_LIMIT).map((pin) => (
            <li key={pin.key}>{pinLabel(pin)}</li>
          ))}
          {group.members.length > LIST_LIMIT ? (
            <li>+{group.members.length - LIST_LIMIT} more</li>
          ) : null}
        </ul>
      ) : null}
    </>
  );
}

interface PlacePinsProps {
  map: MaplibreMap | null;
  pins: readonly KeyedPin[];
}

/**
 * Pins for the places behind the selected factors, one MapLibre HTML marker
 * per pin or cluster. Clusters are recomputed in screen space after every
 * move; markers are diffed by key so unchanged ones are never rebuilt.
 */
export function PlacePins({ map, pins }: PlacePinsProps) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const live = useRef(new Map<string, { marker: Marker; entry: Entry }>());

  useEffect(() => {
    const registry = live.current;
    if (!map || pins.length === 0) return;

    const sync = () => {
      const groups = groupPins(map, pins);
      const keep = new Set(groups.map((group) => group.key));
      for (const [key, { marker }] of registry) {
        if (!keep.has(key)) {
          safeRemove(marker);
          registry.delete(key);
        }
      }
      for (const group of groups) {
        if (registry.has(group.key)) continue;
        const element = document.createElement("div");
        element.className = styles.anchor;
        const marker = new Marker({ element })
          .setLngLat([group.lon, group.lat])
          .addTo(map);
        registry.set(group.key, { marker, entry: { group, element } });
      }
      setEntries(Array.from(registry.values(), ({ entry }) => entry));
    };

    sync();
    const close = () => setOpenKey(null);
    map.on("moveend", sync);
    map.on("movestart", close);
    return () => {
      try {
        map.off("moveend", sync);
        map.off("movestart", close);
      } catch {
        // The map was removed first.
      }
      for (const { marker } of registry.values()) safeRemove(marker);
      registry.clear();
      setEntries([]);
      setOpenKey(null);
    };
  }, [map, pins]);

  const toggle = (key: string) => setOpenKey((current) => (current === key ? null : key));

  const zoomInto = (group: PinGroup) => {
    if (!map) return;
    const points = group.members.map((pin) => map.project([pin.longitude, pin.latitude]));
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const spread = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    if (map.getZoom() >= EXPAND_ZOOM || spread < MIN_SPREAD_PX) {
      toggle(group.key);
      return;
    }
    const lons = group.members.map((pin) => pin.longitude);
    const lats = group.members.map((pin) => pin.latitude);
    map.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { padding: 80, maxZoom: MAX_ZOOM, animate: !prefersReducedMotion() },
    );
  };

  return (
    <>
      {entries.map(({ group, element }) =>
        createPortal(
          group.members.length === 1 ? (
            <SinglePin
              group={group}
              open={openKey === group.key}
              onToggle={toggle}
              onZoom={zoomInto}
            />
          ) : (
            <ClusterPin
              group={group}
              open={openKey === group.key}
              onToggle={toggle}
              onZoom={zoomInto}
            />
          ),
          element,
          group.key,
        ),
      )}
    </>
  );
}
