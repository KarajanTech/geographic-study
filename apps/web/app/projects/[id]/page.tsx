import Link from "next/link";
import { notFound } from "next/navigation";

import type {
  AnalysisRun,
  BoundsWGS84,
  CandidateSite,
  Dataset,
  Project,
  Viewshed,
} from "@sentinel/shared-schemas";

import { CandidateTable } from "@/components/candidate-table";
import { DatasetTable } from "@/components/dataset-table";
import { StudyAreaMap } from "@/components/study-area-map";
import { ViewshedTable } from "@/components/viewshed-table";
import {
  ApiError,
  datasetDownloadUrl,
  datasetPreviewUrl,
  getProject,
  listAnalysisRuns,
  listCandidates,
  listProjectDatasets,
  listViewsheds,
  viewshedPreviewUrl,
} from "@/lib/api-client";
import {
  formatArea,
  formatCoordinate,
  formatDate,
  formatNumber,
  formatPercent,
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

  const processed = datasets.find((dataset) => dataset.role === "processed");
  const raw = datasets.find((dataset) => dataset.role === "raw");
  const previewBounds = previewBoundsOf(processed);
  const validRatio = validRatioOf(processed);

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
  const viewshedOverlays = viewsheds
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
        <StudyAreaMap
          area={project.area}
          previewUrl={processed ? datasetPreviewUrl(processed.id) : null}
          previewBounds={previewBounds}
          candidates={candidates}
          viewshedOverlays={viewshedOverlays}
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
              <dd>{formatNumber(Number(latestCandidateRun.parameters["spacing_m"] ?? 0), 0)} m</dd>
              <dt>Max slope</dt>
              <dd>
                {formatNumber(Number(latestCandidateRun.parameters["max_slope_deg"] ?? 0), 1)}°
              </dd>
              <dt>Generated</dt>
              <dd>{formatDate(latestCandidateRun.created_at)}</dd>
            </dl>
            <CandidateTable candidates={candidates} />
          </>
        ) : (
          <p className="subtitle">
            No candidates generated yet. Run{" "}
            <code>POST /api/v1/projects/{project.id}/candidates</code> against a project with a
            processed DEM.
          </p>
        )}
      </section>

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
            <ViewshedTable viewsheds={viewsheds} />
          </>
        ) : (
          <p className="subtitle">
            No viewsheds generated yet. Run{" "}
            <code>
              POST /api/v1/analysis-runs/{latestCandidateRun?.id ?? "&lt;candidates-run-id&gt;"}
              /viewsheds
            </code>{" "}
            against a project with candidate sites, then let the worker process it.
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Datasets</h2>
        <DatasetTable datasets={datasets} />
      </section>
    </main>
  );
}
