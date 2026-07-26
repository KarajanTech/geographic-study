"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, enqueueViewsheds } from "@/lib/api-client";

/** Step: queue viewshed computation for a candidate run's sites. */
export function ViewshedForm({ candidatesRunId }: { candidatesRunId: string }): React.ReactElement {
  const router = useRouter();
  const [observerHeightM, setObserverHeightM] = useState(10);
  const [targetHeightM, setTargetHeightM] = useState(0);
  const [maxDistanceM, setMaxDistanceM] = useState(5000);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await enqueueViewsheds(candidatesRunId, {
        observer_height_m: observerHeightM,
        target_height_m: targetHeightM,
        max_distance_m: maxDistanceM,
        use_earth_curvature: true,
        refraction_coefficient: 0.13,
      });
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Unexpected error queuing viewsheds.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <p className="subtitle">
        Queue line-of-sight computation for every candidate. A worker processes the queue; this page
        updates automatically while it runs.
      </p>
      <div className="form-row">
        <div className="form-field">
          <label htmlFor="observer-height-m">Sentinel pole height (m)</label>
          <input
            id="observer-height-m"
            type="number"
            min={0}
            max={200}
            step={0.5}
            value={observerHeightM}
            onChange={(event) => setObserverHeightM(Number(event.target.value))}
          />
        </div>
        <div className="form-field">
          <label htmlFor="target-height-m">Target height (m)</label>
          <input
            id="target-height-m"
            type="number"
            min={0}
            max={200}
            step={0.5}
            value={targetHeightM}
            onChange={(event) => setTargetHeightM(Number(event.target.value))}
          />
        </div>
        <div className="form-field">
          <label htmlFor="max-distance-m">Sight range (m)</label>
          <input
            id="max-distance-m"
            type="number"
            min={100}
            max={50000}
            step={100}
            value={maxDistanceM}
            onChange={(event) => setMaxDistanceM(Number(event.target.value))}
          />
        </div>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? "Queuing…" : "Compute viewsheds"}
      </button>
    </form>
  );
}
