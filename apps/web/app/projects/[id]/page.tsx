import Link from "next/link";
import { notFound } from "next/navigation";

import type { BoundsWGS84, Dataset, Project } from "@sentinel/shared-schemas";

import { DatasetTable } from "@/components/dataset-table";
import { StudyAreaMap } from "@/components/study-area-map";
import {
  ApiError,
  datasetDownloadUrl,
  datasetPreviewUrl,
  getProject,
  listProjectDatasets,
} from "@/lib/api-client";
import { formatArea, formatCoordinate, formatDate, formatPercent } from "@/lib/format";

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
  try {
    [project, datasets] = await Promise.all([
      getProject(id),
      listProjectDatasets(id).then((list) => list.items),
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
        <h2>Datasets</h2>
        <DatasetTable datasets={datasets} />
      </section>
    </main>
  );
}
