import Link from "next/link";

import type { ProjectList } from "@sentinel/shared-schemas";

import { ApiError, listProjects } from "@/lib/api-client";
import { formatArea, formatCoordinate, formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ProjectsPage(): Promise<React.ReactElement> {
  let projects: ProjectList | null = null;
  let error: string | null = null;

  try {
    projects = await listProjects();
  } catch (cause) {
    error = cause instanceof ApiError ? cause.message : "Unexpected error contacting the API.";
  }

  return (
    <main>
      <p className="breadcrumb">
        <Link href="/">← System status</Link>
      </p>
      <h1>Projects</h1>
      <p className="subtitle">
        A project is a study area plus the projected metric CRS every calculation for it uses.
      </p>
      <p>
        <Link href="/projects/new">+ New project</Link>
      </p>

      {error !== null ? (
        <section className="panel">
          <h2>API</h2>
          <p>
            <span className="status status-down">unreachable</span>
          </p>
          <p className="subtitle">{error}</p>
        </section>
      ) : null}

      {projects && projects.items.length === 0 ? (
        <section className="panel">
          <h2>No projects yet</h2>
          <p className="subtitle">
            <Link href="/projects/new">Create one</Link> by drawing a study area, or run{" "}
            <code>make demo-project</code> to seed a demonstration study area with a synthetic DEM.
          </p>
        </section>
      ) : null}

      {projects?.items.map((project) => (
        <section className="panel" key={project.id}>
          <h2>
            <Link href={`/projects/${project.id}`}>{project.name}</Link>
          </h2>
          {project.description ? <p className="subtitle">{project.description}</p> : null}
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
            <dt>Datasets</dt>
            <dd>{project.dataset_count}</dd>
            <dt>Created</dt>
            <dd>{formatDate(project.created_at)}</dd>
          </dl>
        </section>
      ))}
    </main>
  );
}
