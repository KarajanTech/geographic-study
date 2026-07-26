import type { CandidateSite, OptimizationIteration } from "@sentinel/shared-schemas";

import { formatNumber, formatPercent } from "@/lib/format";

/**
 * Ordered table of selected Sentinel positions, doubling as the
 * units-vs-coverage curve: each row's bar shows cumulative weighted coverage
 * after that pick, so the curve is read top to bottom.
 */
export function OptimizationTable({
  iterations,
  candidatesById,
}: {
  iterations: OptimizationIteration[];
  candidatesById: Record<string, CandidateSite>;
}): React.ReactElement {
  if (iterations.length === 0) {
    return <p className="subtitle">No Sentinel selected in this solution.</p>;
  }

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Longitude</th>
            <th>Latitude</th>
            <th>Elevation</th>
            <th>Marginal gain</th>
            <th>Cumulative coverage</th>
          </tr>
        </thead>
        <tbody>
          {iterations.map((entry) => {
            const candidate = candidatesById[entry.candidate_id];
            const [lon, lat] = candidate?.location.coordinates ?? [];
            return (
              <tr key={entry.candidate_id}>
                <td>{entry.step + 1}</td>
                <td>{lon !== undefined ? `${formatNumber(lon, 5)}°` : "—"}</td>
                <td>{lat !== undefined ? `${formatNumber(lat, 5)}°` : "—"}</td>
                <td>{candidate ? `${formatNumber(candidate.elevation_m, 1)} m` : "—"}</td>
                <td>{formatNumber(entry.marginal_gain, 0)} cells</td>
                <td>
                  <div className="coverage-cell">
                    <div
                      className="coverage-bar"
                      style={{
                        width: `${Math.min(100, entry.cumulative_weighted_coverage * 100)}%`,
                      }}
                    />
                    <span>{formatPercent(entry.cumulative_weighted_coverage)}</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
