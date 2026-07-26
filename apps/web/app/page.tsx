import Link from "next/link";

import type { HealthResponse, ReadinessResponse } from "@sentinel/shared-schemas";

import { SystemStatus } from "@/components/system-status";
import { ApiError, getHealth, getReadiness } from "@/lib/api-client";

// Health is live state: never statically rendered at build time.
export const dynamic = "force-dynamic";

interface PageData {
  health: HealthResponse | null;
  readiness: ReadinessResponse | null;
  error: string | null;
}

async function loadStatus(): Promise<PageData> {
  try {
    const [health, readiness] = await Promise.all([getHealth(), getReadiness()]);
    return { health, readiness: readiness.payload, error: null };
  } catch (cause) {
    const message =
      cause instanceof ApiError ? cause.message : "Unexpected error while contacting the API.";
    return { health: null, readiness: null, error: message };
  }
}

export default async function HomePage(): Promise<React.ReactElement> {
  const { health, readiness, error } = await loadStatus();

  return (
    <main>
      <h1>Sentinel Planner</h1>
      <p className="subtitle">Geospatial planning of wildfire surveillance tower networks.</p>

      <SystemStatus health={health} readiness={readiness} error={error} />

      <section className="panel">
        <h2>Projects</h2>
        <p className="subtitle">
          A project is a study area plus the projected metric CRS every calculation for it uses.
        </p>
        <p>
          <Link href="/projects">Browse study areas and their terrain →</Link>
        </p>
      </section>

      <section className="panel">
        <h2>Roadmap</h2>
        <ul className="roadmap">
          <li>Phase 0 — foundation: monorepo, API, database, CI.</li>
          <li>Phase 1 — geospatial ingestion: DEM upload, validation, reprojection, clipping.</li>
          <li>
            Phase 2 — candidate generation: grid, slope and prominence filtering, minimum
            separation.
          </li>
          <li>Phase 3 — viewshed engine: line-of-sight computation, caching, worker execution.</li>
          <li>
            Phase 4 — greedy maximum coverage optimizer: candidate-cell matrix, deterministic
            tie-breaking, units-vs-coverage curve.
          </li>
          <li>
            Phase 5 — usable MVP interface: draw a study area on a real map, upload a DEM, configure
            and launch each step, watch progress, export the result.
          </li>
          <li>
            <strong>Phase 6 — risk-weighted coverage:</strong> upload a priority raster or pick a
            terrain preset, boost priority zones, physical vs. weighted coverage reported and saved
            separately. Current phase.
          </li>
        </ul>
      </section>
    </main>
  );
}
