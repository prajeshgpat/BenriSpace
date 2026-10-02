import { redirect } from "next/navigation";

import { legacyMapQuery } from "@/lib/map/url";

/** `/map` was merged into the home page; old shared links keep working. */
export default async function LegacyMapPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = legacyMapQuery(await searchParams);
  redirect(query ? `/?${query}` : "/");
}
