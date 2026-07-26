import Link from "next/link";
import { notFound } from "next/navigation";

import type {
  AnalysisRun,
  BoundsWGS84,
  CandidateSite,
  Dataset,
  OptimizationSolution,
  Project,
  Viewshed,
} from "@sentinel/shared-schemas";

import { AnalysisProgress } from "@/components/analysis-progress";
import { CandidateForm } from "@/components/candidate-form";
import { CandidateTable } from "@/components/candidate-table";
import { DatasetTable } from "@/components/dataset-table";
import { DatasetUploadForm } from "@/components/dataset-upload-form";
import { InteractiveMap } from "@/components/interactive-map-loader";
import { OptimizationForm } from "@/components/optimization-form";
import { OptimizationTable } from "@/components/optimization-table";
import { PrioritiesUploadForm } from "@/components/priorities-upload-form";
import { ViewshedForm } from "@/components/viewshed-form";
import { ViewshedTable } from "@/components/viewshed-table";
import {
  ApiError,
  datasetDownloadUrl,
  datasetPreviewUrl,
  getProject,
  listAnalysisRuns,
  listCandidates,
  listOptimizationSolutions,
  listProjectDatasets,
  listViewsheds,
  optimizationSolutionCsvUrl,
  optimizationSolutionGeoJsonUrl,
  viewshedPreviewUrl,
} from "@/lib/api-client";
import {
  formatArea,
  formatCoordinate,
  formatDate,
  formatNumber,
  formatPercent,
  shortId,
} from "@/lib/format";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** Reads the preview extent the backend stored with the processed dataset. */
function previewBoundsOf(dataset: Dataset | undefined): BoundsWGS84 | null {
  const raw = dataset?.metadata?.["preview_bounds_wgs84"];
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const bounds = raw as Record<string, unknown>;
  const [west, south, east, north] = [
    bounds["left"],
    bounds["bottom"],
    bounds["right"],
    bounds["top"],
  ];
  if (
    typeof west !== "number" ||
    typeof south !== "number" ||
    typeof east !== "number" ||
    typeof north !== "number"
  ) {
    return null;
  }
  return { west, south, east, north };
}

function validRatioOf(dataset: Dataset | undefined): number | null {
  const ratio = dataset?.metadata?.["valid_ratio"];
  return typeof ratio === "number" ? ratio : null;
}

/** Human-readable summary of an OptimizationSolution's persisted weights_summary. */
function describeWeights(summary: Record<string, unknown> | null): string {
  if (!summary) return "unknown";

  const source = summary["source"];
  const parts: string[] = [];
  if (source === "preset") {
    parts.push(`preset: ${String(summary["preset"]).replaceAll("_", " ")}`);
  } else if (source === "raster") {
    parts.push("uploaded risk raster");
  } else {
    parts.push("uniform (every cell counts equally)");
  }

  const zones = summary["priority_zones"];
  if (Array.isArray(zones) && zones.length > 0) {
    const weights = zones
      .map((zone) =>
        typeof zone === "object" && zone !== null
          ? (zone as Record<string, unknown>)["weight"]
          : undefined,
      )
      .filter((weight): weight is number => typeof weight === "number");
    if (weights.length > 0) {
      const label = weights.length > 1 ? "zones" : "zone";
      parts.push(`+ ${weights.length} priority ${label} (×${weights.join(", ×")})`);
    }
  }

  return parts.join(" ");
}

export default async function ProjectPage({ params }: PageProps): Promise<React.ReactElement> {
  const { id } = await params;

  let project: Project;
  let datasets: Dataset[];
  let analysisRuns: AnalysisRun[];
  try {
    [project, datasets, analysisRuns] = await Promise.all([
      getProject(id),
      listProjectDatasets(id).then((list) => list.items),
      listAnalysisRuns(id).then((list) => list.items),
    ]);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      notFound();
    }
    throw cause;
  }

  const processed = datasets.find(
    (dataset) => dataset.role === "processed" && dataset.dataset_type === "dem",
  );
  const raw = datasets.find((dataset) => dataset.role === "raw" && dataset.dataset_type === "dem");
  const previewBounds = previewBoundsOf(processed);
  const validRatio = validRatioOf(processed);
  const activePriorities = datasets
    .filter((dataset) => dataset.dataset_type === "priorities" && dataset.role === "processed")
    .at(-1); // most recently uploaded, matching the backend's "active" definition

  const latestCandidateRun = analysisRuns
    .filter((run) => run.kind === "candidates" && run.status === "completed")
    .at(0); // the API lists runs newest first
  const candidates: CandidateSite[] = latestCandidateRun
    ? (await listCandidates(latestCandidateRun.id)).items
    : [];

  const latestViewshedRun = analysisRuns.filter((run) => run.kind === "viewshed").at(0); // pending/running runs are shown too, so progress is visible
  const viewsheds: Viewshed[] = latestViewshedRun
    ? (await listViewsheds(latestViewshedRun.id)).items
    : [];

  const latestOptimizationRun = analysisRuns.filter((run) => run.kind === "optimization").at(0);
  const optimizationSolution: OptimizationSolution | undefined = latestOptimizationRun
    ? (await listOptimizationSolutions(latestOptimizationRun.id)).items.at(0)
    : undefined;
  const selectedCandidateIds = new Set(optimizationSolution?.selected_candidate_ids ?? []);
  const candidatesById = Object.fromEntries(candidates.map((c) => [c.id, c]));

  const viewshedsById = Object.fromEntries(viewsheds.map((v) => [v.candidate_site_id, v]));
  // When a solution exists, show only the chosen Sentinel's coverage — the
  // "mapa de cobertura acumulada" deliverable — instead of every computed
  // viewshed overlapping at once.
  const overlaySource = optimizationSolution
    ? optimizationSolution.selected_candidate_ids
        .map((candidateId) => viewshedsById[candidateId])
        .filter((v): v is Viewshed => v !== undefined)
    : viewsheds;
  const viewshedOverlays = overlaySource
    .filter((v) => v.status === "completed" && v.preview_url && v.bounds_wgs84)
    .map((v) => ({ id: v.id, url: viewshedPreviewUrl(v.id), bounds: v.bounds_wgs84! }));

  return (
    <main>
      <p className="breadcrumb">
        <Link href="/projects">← Projects</Link>
      </p>
      <h1>{project.name}</h1>
      <p className="subtitle">
        {project.description ?? "Study area and its analysis-ready surface."}
      </p>

      <section className="panel">
        <h2>Study area</h2>
        <InteractiveMap
          key={`${candidates.length}-${viewshedOverlays.length}-${optimizationSolution?.id ?? "none"}`}
          mode="view"
          initialArea={project.area}
          previewUrl={processed ? datasetPreviewUrl(processed.id) : null}
          previewBounds={previewBounds}
          candidates={candidates}
          viewshedOverlays={viewshedOverlays}
          selectedCandidateIds={selectedCandidateIds}
        />
      </section>

      <section className="panel">
        <h2>Project</h2>
        <dl>
          <dt>Analysis CRS</dt>
          <dd>
            <code>{project.analysis_crs}</code>
          </dd>
          <dt>Area</dt>
          <dd>{formatArea(project.area_km2)}</dd>
          <dt>Centroid</dt>
          <dd>
            {formatCoordinate(project.centroid_lat)}, {formatCoordinate(project.centroid_lon)}
          </dd>
          <dt>Created</dt>
          <dd>{formatDate(project.created_at)}</dd>
        </dl>
      </section>

      {!processed ? (
        <section className="panel">
          <h2>Ingest a DEM</h2>
          <DatasetUploadForm projectId={project.id} />
        </section>
      ) : null}

      {processed ? (
        <section className="panel">
          <h2>Analysis surface</h2>
          <dl>
            <dt>CRS</dt>
            <dd>
              <code>{processed.crs}</code> ({processed.units})
            </dd>
            <dt>Extent</dt>
            <dd>
              {processed.bounds
                ? `${Math.round(processed.bounds.right - processed.bounds.left)} × ${Math.round(
                    processed.bounds.top - processed.bounds.bottom,
                  )} m`
                : "unknown"}
            </dd>
            <dt>Cells with data</dt>
            <dd>{validRatio === null ? "unknown" : formatPercent(validRatio)}</dd>
            <dt>Source</dt>
            <dd>{raw?.original_filename ?? "—"}</dd>
            <dt>Download</dt>
            <dd>
              <a href={datasetDownloadUrl(processed.id)}>GeoTIFF</a>
            </dd>
          </dl>
        </section>
      ) : null}

      {processed && processed.processing_history.length > 0 ? (
        <section className="panel">
          <h2>Processing history</h2>
          <ol className="history">
            {processed.processing_history.map((entry, index) => (
              <li key={index}>
                <strong>{String(entry["step"])}</strong>
                <code>{JSON.stringify(entry)}</code>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {processed ? (
        <section className="panel">
          <h2>Risk / priority weighting</h2>
          {activePriorities ? (
            <dl>
              <dt>Active raster</dt>
              <dd>{activePriorities.original_filename ?? shortId(activePriorities.id)}</dd>
              <dt>Preview</dt>
              <dd>
                <a href={datasetPreviewUrl(activePriorities.id, "preview")}>PNG</a>
              </dd>
            </dl>
          ) : (
            <p className="subtitle">
              No risk raster uploaded yet. Without one, the optimizer treats every cell equally
              unless you pick a preset when running it.
            </p>
          )}
          <PrioritiesUploadForm projectId={project.id} />
        </section>
      ) : null}

      {processed ? (
        <section className="panel">
          <h2>Candidate sites</h2>
          {latestCandidateRun ? (
            <>
              <dl>
                <dt>Grid points evaluated</dt>
                <dd>
                  {formatNumber(Number(latestCandidateRun.metrics["grid_point_count"] ?? 0), 0)}
                </dd>
                <dt>Accepted candidates</dt>
                <dd>{candidates.length}</dd>
                <dt>Spacing</dt>
                <dd>
                  {formatNumber(Number(latestCandidateRun.parameters["spacing_m"] ?? 0), 0)} m
                </dd>
                <dt>Max slope</dt>
                <dd>
                  {formatNumber(Number(latestCandidateRun.parameters["max_slope_deg"] ?? 0), 1)}°
                </dd>
                <dt>Generated</dt>
                <dd>{formatDate(latestCandidateRun.created_at)}</dd>
              </dl>
              <CandidateTable candidates={candidates} />
            </>
          ) : null}
          <CandidateForm projectId={project.id} />
        </section>
      ) : null}

      {latestCandidateRun ? (
        <section className="panel">
          <h2>Viewsheds</h2>
          {latestViewshedRun ? (
            <>
              <dl>
                <dt>Status</dt>
                <dd>
                  <span
                    className={`status status-${latestViewshedRun.status === "completed" ? "up" : latestViewshedRun.status === "failed" ? "down" : "not_configured"}`}
                  >
                    {latestViewshedRun.status}
                  </span>
                </dd>
                <dt>Progress</dt>
                <dd>
                  {formatNumber(Number(latestViewshedRun.metrics["completed"] ?? 0), 0)} completed,{" "}
                  {formatNumber(Number(latestViewshedRun.metrics["failed"] ?? 0), 0)} failed,{" "}
                  {formatNumber(Number(latestViewshedRun.metrics["pending"] ?? 0), 0)} pending
                </dd>
                <dt>Cache hits</dt>
                <dd>{formatNumber(Number(latestViewshedRun.metrics["cache_hits"] ?? 0), 0)}</dd>
                <dt>Range</dt>
                <dd>
                  {formatNumber(Number(latestViewshedRun.parameters["max_distance_m"] ?? 0), 0)} m
                </dd>
                <dt>Requested</dt>
                <dd>{formatDate(latestViewshedRun.created_at)}</dd>
              </dl>
              <AnalysisProgress key={latestViewshedRun.id} run={latestViewshedRun} />
              <ViewshedTable viewsheds={viewsheds} />
            </>
          ) : null}
          <ViewshedForm candidatesRunId={latestCandidateRun.id} />
        </section>
      ) : null}

      {latestViewshedRun ? (
        <section className="panel">
          <h2>Optimization</h2>
          {optimizationSolution ? (
            <>
              <dl>
                <dt>Solver</dt>
                <dd>{optimizationSolution.solver}</dd>
                <dt>Stop reason</dt>
                <dd>{optimizationSolution.stop_reason.replaceAll("_", " ")}</dd>
                <dt>Sentinel selected</dt>
                <dd>{optimizationSolution.selected_candidate_ids.length}</dd>
                <dt>Coverage</dt>
                <dd>{formatPercent(optimizationSolution.coverage_ratio)}</dd>
                <dt>Weighted coverage</dt>
                <dd>{formatPercent(optimizationSolution.weighted_coverage_ratio)}</dd>
                <dt>Visible surface</dt>
                <dd>{formatArea(optimizationSolution.visible_area_km2)}</dd>
                <dt>Hidden surface</dt>
                <dd>{formatArea(optimizationSolution.hidden_area_km2)}</dd>
                <dt>Runtime</dt>
                <dd>{formatNumber(optimizationSolution.runtime_seconds, 3)} s</dd>
                <dt>Weights used</dt>
                <dd>{describeWeights(optimizationSolution.weights_summary)}</dd>
                <dt>Export</dt>
                <dd>
                  <a href={optimizationSolutionGeoJsonUrl(optimizationSolution.id)}>GeoJSON</a>
                  {" · "}
                  <a href={optimizationSolutionCsvUrl(optimizationSolution.id)}>CSV</a>
                </dd>
              </dl>
              <OptimizationTable
                iterations={optimizationSolution.iterations}
                candidatesById={candidatesById}
              />
            </>
          ) : null}
          <OptimizationForm
            viewshedRunId={latestViewshedRun.id}
            prioritiesDatasetId={activePriorities?.id ?? null}
          />
        </section>
      ) : null}

      <section className="panel">
        <h2>Datasets</h2>
        <DatasetTable datasets={datasets} />
      </section>
    </main>
  );
}
