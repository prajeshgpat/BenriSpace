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

export const GasConvenienceIcon = icon(
  "gasConvenience",
  <>
    <path d="M4 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M3 21h12M6 8h6" />
    <path d="M14 10h2a2 2 0 0 1 2 2v4a1.5 1.5 0 0 0 3 0V8l-3-3" />
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

export const TrafficIcon = icon(
  "traffic",
  <>
    <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2" />
    <circle cx="7" cy="17" r="2" />
    <path d="M9 17h6" />
    <circle cx="17" cy="17" r="2" />
  </>,
);

export const EmergencyCorridorIcon = icon(
  "emergencyCorridor",
  <>
    <path d="M7 18v-6a5 5 0 1 1 10 0v6" />
    <path d="M5 21a1 1 0 0 0 1-1v-1a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1a1 1 0 0 0 1 1z" />
    <path d="M21 12h1M2 12h1M12 2v1M4.9 4.9l.7.7M19.1 4.9l-.7.7M12 12v6" />
  </>,
);

/** A real airplane silhouette (not the paper-plane "send" arrow). */
export const AirportIcon = icon(
  "airport",
  <>
    <path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" />
  </>,
);

export const ShoppingIcon = icon(
  "shopping",
  <>
    <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
    <path d="M3 6h18" />
    <path d="M16 10a4 4 0 0 1-8 0" />
  </>,
);

export const RecreationIcon = icon(
  "recreation",
  <>
    <path d="M12 3l4.5 6H14l4.5 6h-13L10 9H7.5z" />
    <path d="M12 15v6" />
  </>,
);

export const FACTOR_ICONS: Record<FactorKey, ComponentType<FactorIconProps>> = {
  grocery: GroceryIcon,
  restaurant: RestaurantIcon,
  cafe: CafeIcon,
  bar: BarIcon,
  gym: GymIcon,
  shopping: ShoppingIcon,
  transit: TransitIcon,
  airport: AirportIcon,
  gasConvenience: GasConvenienceIcon,
  traffic: TrafficIcon,
  school: SchoolIcon,
  emergencyCorridor: EmergencyCorridorIcon,
  recreation: RecreationIcon,
};

/** The icon for a factor key; decorative, so it always sits next to the label. */
export function FactorIcon({
  factor,
  ...props
}: FactorIconProps & { factor: FactorKey }) {
  const Icon = FACTOR_ICONS[factor];
  return <Icon {...props} />;
}
