import type { Dataset } from "@sentinel/shared-schemas";

import { formatBytes, formatDate, formatResolution, shortId } from "@/lib/format";

/** Presentational table of a project's datasets. */
export function DatasetTable({ datasets }: { datasets: Dataset[] }): React.ReactElement {
  if (datasets.length === 0) {
    return (
      <p className="subtitle">
        No datasets yet. Upload a DEM with <code>POST /api/v1/projects/&lt;id&gt;/datasets</code>.
      </p>
    );
  }

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Role</th>
            <th>Status</th>
            <th>CRS</th>
            <th>Resolution</th>
            <th>Nodata</th>
            <th>Size</th>
            <th>Checksum</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((dataset) => (
            <tr key={dataset.id}>
              <td>{dataset.role}</td>
              <td>
                <span className={`status status-${dataset.status === "ready" ? "up" : "down"}`}>
                  {dataset.status}
                </span>
              </td>
              <td>
                <code>{dataset.crs ?? "none"}</code>
              </td>
              <td>{formatResolution(dataset.resolution_x, dataset.resolution_y, dataset.units)}</td>
              <td>{dataset.nodata ?? "—"}</td>
              <td>{formatBytes(dataset.size_bytes)}</td>
              <td>
                <code title={dataset.checksum_sha256}>{shortId(dataset.checksum_sha256)}</code>
              </td>
              <td>{formatDate(dataset.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
