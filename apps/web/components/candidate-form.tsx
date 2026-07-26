"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, generateCandidates } from "@/lib/api-client";

/** Step: generate candidate Sentinel positions over the ingested surface. */
export function CandidateForm({ projectId }: { projectId: string }): React.ReactElement {
  const router = useRouter();
  const [spacingM, setSpacingM] = useState(300);
  const [maxSlopeDeg, setMaxSlopeDeg] = useState(25);
  const [minSeparationM, setMinSeparationM] = useState(300);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await generateCandidates(projectId, {
        spacing_m: spacingM,
        max_slope_deg: maxSlopeDeg,
        min_separation_m: minSeparationM,
        jitter_m: 0,
        prominence_radius_m: 1000,
        seed: 20240101,
      });
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Unexpected error generating candidates.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <p className="subtitle">
        Lay a regular grid of candidate Sentinel positions and filter it by slope and separation.
      </p>
      <div className="form-row">
        <div className="form-field">
          <label htmlFor="spacing-m">Grid spacing (m)</label>
          <input
            id="spacing-m"
            type="number"
            min={10}
            max={20000}
            step={10}
            value={spacingM}
            onChange={(event) => setSpacingM(Number(event.target.value))}
          />
        </div>
        <div className="form-field">
          <label htmlFor="max-slope-deg">Maximum slope (°)</label>
          <input
            id="max-slope-deg"
            type="number"
            min={0}
            max={90}
            step={1}
            value={maxSlopeDeg}
            onChange={(event) => setMaxSlopeDeg(Number(event.target.value))}
          />
        </div>
        <div className="form-field">
          <label htmlFor="min-separation-m">Minimum separation (m)</label>
          <input
            id="min-separation-m"
            type="number"
            min={0}
            max={50000}
            step={10}
            value={minSeparationM}
            onChange={(event) => setMinSeparationM(Number(event.target.value))}
          />
        </div>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? "Generating…" : "Generate candidates"}
      </button>
    </form>
  );
}
