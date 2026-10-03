import type { ComponentType, ReactNode, SVGProps } from "react";

import type { FactorKey } from "@/lib/api/types";

export type FactorIconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function icon(name: string, paths: ReactNode): ComponentType<FactorIconProps> {
  function Icon(props: FactorIconProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={16}
        height={16}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        data-icon={name}
        {...props}
      >
        {paths}
      </svg>
    );
  }
  Icon.displayName = `${name}Icon`;
  return Icon;
}

export const GroceryIcon = icon(
  "grocery",
  <>
    <circle cx="9" cy="20" r="1" />
    <circle cx="18" cy="20" r="1" />
    <path d="M2 3h3l2.7 11.4a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 7H6" />
  </>,
);

export const GymIcon = icon(
  "gym",
  <>
    <path d="M6 7v10M18 7v10M3 9.5v5M21 9.5v5M6 12h12" />
  </>,
);

export const CafeIcon = icon(
  "cafe",
  <>
    <path d="M4 9h13v6a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z" />
    <path d="M17 11h1.5a2.5 2.5 0 0 1 0 5H17M8 2v3M12 2v3" />
  </>,
);

export const RestaurantIcon = icon(
  "restaurant",
  <>
    <path d="M6 3v7a2 2 0 0 0 2 2v9M10 3v7a2 2 0 0 1-2 2M8 3v9" />
    <path d="M17 21V3c-2 1.5-3 4-3 7s1 4 3 4" />
  </>,
);

export const BarIcon = icon(
  "bar",
  <>
    <path d="M5 4h14l-7 8zM12 12v8M8 20h8" />
  </>,
);

export const GasStationIcon = icon(
  "gasStation",
  <>
    <path d="M4 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M3 21h12M6 8h6" />
    <path d="M14 10h2a2 2 0 0 1 2 2v4a1.5 1.5 0 0 0 3 0V8l-3-3" />
  </>,
);

export const ConvenienceStoreIcon = icon(
  "convenienceStore",
  <>
    <path d="M3 9l1.5-5h15L21 9M3 9h18M3 9a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0" />
    <path d="M5 12v9h14v-9M10 21v-5h4v5" />
  </>,
);

export const TransitIcon = icon(
  "transit",
  <>
    <rect x="5" y="3" width="14" height="14" rx="3" />
    <path d="M5 11h14M9 21l2-4M15 21l-2-4" />
    <circle cx="9" cy="14" r=".5" />
    <circle cx="15" cy="14" r=".5" />
  </>,
);

export const SchoolIcon = icon(
  "school",
  <>
    <path d="M2 9l10-5 10 5-10 5z" />
    <path d="M6 11.5V16c0 1.5 2.7 3 6 3s6-1.5 6-3v-4.5M22 9v6" />
  </>,
);

export const RoadIcon = icon(
  "road",
  <>
    <path d="M8 3L4 21M16 3l4 18M12 4v3M12 11v3M12 18v3" />
  </>,
);

export const EmergencyCorridorIcon = icon(
  "emergencyCorridor",
  <>
    <path d="M4 10v4h3l5 4V6L7 10zM16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12" />
  </>,
);

export const AirportIcon = icon(
  "airport",
  <>
    <path d="M10.5 13.5L3 11l1.5-1.5 8-.5L16 5a2 2 0 0 1 3 3l-4 3.5.5 8L14 21l-2.5-7.5" />
  </>,
);

export const PremiumRetailIcon = icon(
  "premiumRetail",
  <>
    <path d="M6 3h12l3 6-9 12L3 9z" />
    <path d="M3 9h18M9 3l-2 6 5 12M15 3l2 6-5 12" />
  </>,
);

export const TrailPopularityIcon = icon(
  "trailPopularity",
  <>
    <path d="M3 20c4 0 4-5 8-5s3-6 6-6 2-5 4-5" />
    <circle cx="4" cy="20" r="1" />
    <circle cx="20" cy="4" r="1" />
  </>,
);

export const FACTOR_ICONS: Record<FactorKey, ComponentType<FactorIconProps>> = {
  grocery: GroceryIcon,
  gym: GymIcon,
  cafe: CafeIcon,
  restaurant: RestaurantIcon,
  bar: BarIcon,
  premiumRetail: PremiumRetailIcon,
  gasStation: GasStationIcon,
  convenienceStore: ConvenienceStoreIcon,
  transit: TransitIcon,
  school: SchoolIcon,
  road: RoadIcon,
  emergencyCorridor: EmergencyCorridorIcon,
  airport: AirportIcon,
  trailPopularity: TrailPopularityIcon,
};

/** The icon for a factor key; decorative, so it always sits next to the label. */
export function FactorIcon({
  factor,
  ...props
}: FactorIconProps & { factor: FactorKey }) {
  const Icon = FACTOR_ICONS[factor];
  return <Icon {...props} />;
}
