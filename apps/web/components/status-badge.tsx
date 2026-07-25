import type { ComponentStatus } from "@sentinel/shared-schemas";

const LABELS: Record<ComponentStatus, string> = {
  up: "up",
  down: "down",
  not_configured: "not configured",
};

/** Presentational only: renders a dependency status, decides nothing. */
export function StatusBadge({ status }: { status: ComponentStatus }): React.ReactElement {
  return <span className={`status status-${status}`}>{LABELS[status]}</span>;
}
