import type { CandidateSite } from "@sentinel/shared-schemas";

import { formatNumber } from "@/lib/format";

/** Presentational table of a run's candidate sites, best ranked first. */
export function CandidateTable({
  candidates,
  limit = 25,
}: {
  candidates: CandidateSite[];
  limit?: number;
}): React.ReactElement {
  if (candidates.length === 0) {
    return <p className="subtitle">No candidate sites in this run.</p>;
  }

  const shown = candidates.slice(0, limit);

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Longitude</th>
            <th>Latitude</th>
            <th>Elevation</th>
            <th>Slope</th>
            <th>Prominence</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((candidate) => (
            <tr key={candidate.id}>
              <td>{candidate.rank}</td>
              <td>{formatNumber(candidate.location.coordinates[0] ?? 0, 5)}°</td>
              <td>{formatNumber(candidate.location.coordinates[1] ?? 0, 5)}°</td>
              <td>{formatNumber(candidate.elevation_m, 1)} m</td>
              <td>{formatNumber(candidate.slope_deg, 1)}°</td>
              <td>{formatNumber(candidate.prominence_m, 1)} m</td>
              <td>
                {candidate.is_mandatory ? (
                  <span className="status status-down">mandatory</span>
                ) : (
                  candidate.source
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {candidates.length > limit ? (
        <p className="subtitle">
          Showing {shown.length} of {candidates.length} candidates.
        </p>
      ) : null}
    </div>
  );
}
