import type { HealthResponse, ReadinessResponse } from "@sentinel/shared-schemas";

import { StatusBadge } from "./status-badge";

interface SystemStatusProps {
  health: HealthResponse | null;
  readiness: ReadinessResponse | null;
  error: string | null;
}

/**
 * Renders API health. All values are computed by the backend; this component
 * only displays them.
 */
export function SystemStatus({ health, readiness, error }: SystemStatusProps): React.ReactElement {
  if (error !== null) {
    return (
      <section className="panel">
        <h2>API</h2>
        <p>
          <span className="status status-down">unreachable</span>
        </p>
        <p className="subtitle">{error}</p>
      </section>
    );
  }

  return (
    <>
      <section className="panel">
        <h2>API</h2>
        <dl>
          <dt>Status</dt>
          <dd>
            <span className="status status-up">{health?.status ?? "unknown"}</span>
          </dd>
          <dt>Service</dt>
          <dd>
            <code>{health?.service}</code>
          </dd>
          <dt>Version</dt>
          <dd>{health?.version}</dd>
          <dt>Environment</dt>
          <dd>{health?.environment}</dd>
          <dt>Algorithm version</dt>
          <dd>{health?.algorithm_version}</dd>
        </dl>
      </section>

      <section className="panel">
        <h2>Dependencies</h2>
        <dl>
          <dt>Database</dt>
          <dd>{readiness ? <StatusBadge status={readiness.database} /> : "unknown"}</dd>
          <dt>Data directory</dt>
          <dd>{readiness ? <StatusBadge status={readiness.data_dir} /> : "unknown"}</dd>
        </dl>
      </section>
    </>
  );
}
