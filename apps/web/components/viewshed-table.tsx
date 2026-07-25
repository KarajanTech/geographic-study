import type { Viewshed } from "@sentinel/shared-schemas";

import { formatNumber, formatPercent } from "@/lib/format";

/** Presentational table of a batch run's computed viewsheds. */
export function ViewshedTable({
  viewsheds,
  limit = 25,
}: {
  viewsheds: Viewshed[];
  limit?: number;
}): React.ReactElement {
  if (viewsheds.length === 0) {
    return <p className="subtitle">No viewsheds in this run.</p>;
  }

  const shown = viewsheds.slice(0, limit);

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Observer elevation</th>
            <th>Coverage</th>
            <th>Visible cells</th>
            <th>Range</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((viewshed) => (
            <tr key={viewshed.id}>
              <td>
                <span
                  className={`status status-${viewshed.status === "completed" ? "up" : viewshed.status === "failed" ? "down" : "not_configured"}`}
                >
                  {viewshed.status}
                </span>
              </td>
              <td>
                {viewshed.observer_elevation_m != null
                  ? `${formatNumber(viewshed.observer_elevation_m, 1)} m`
                  : "—"}
              </td>
              <td>
                {viewshed.coverage_ratio != null ? formatPercent(viewshed.coverage_ratio) : "—"}
              </td>
              <td>
                {viewshed.visible_cell_count != null
                  ? `${formatNumber(viewshed.visible_cell_count, 0)} / ${formatNumber(viewshed.total_cell_count ?? 0, 0)}`
                  : "—"}
              </td>
              <td>{formatNumber(viewshed.max_distance_m, 0)} m</td>
            </tr>
          ))}
        </tbody>
      </table>
      {viewsheds.length > limit ? (
        <p className="subtitle">
          Showing {shown.length} of {viewsheds.length} viewsheds.
        </p>
      ) : null}
    </div>
  );
}
