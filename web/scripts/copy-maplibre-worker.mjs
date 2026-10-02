// MapLibre starts its tile-parsing worker from a URL it derives from
// import.meta.url, which a bundler rewrites to a file path. Serving the worker
// (and the shared chunk it imports) from /maplibre/ lets the map point at it
// explicitly. They are copied from node_modules rather than committed so they
// always match the installed maplibre-gl version.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(
  dirname(
    createRequire(join(root, "package.json")).resolve(
      "maplibre-gl/package.json",
    ),
  ),
  "dist",
);
const target = join(root, "public", "maplibre");

mkdirSync(target, { recursive: true });
for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  copyFileSync(join(dist, file), join(target, file));
}
