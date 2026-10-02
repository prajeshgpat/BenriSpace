import { redirect } from "next/navigation";

import { legacyMapQuery } from "@/lib/map/url";
import { APP_PATH } from "@/lib/site";

/** `/map` was merged into the app; old shared links keep working. */
export default async function LegacyMapPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = legacyMapQuery(await searchParams);
  redirect(query ? `${APP_PATH}?${query}` : APP_PATH);
}
