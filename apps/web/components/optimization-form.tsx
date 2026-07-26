"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { GeoJSONGeometry } from "@sentinel/shared-schemas";

import { ApiError, optimizeCoverage } from "@/lib/api-client";

import { InteractiveMap } from "./interactive-map-loader";

type Preset = "" | "uniform" | "ridge_priority" | "valley_priority";

/** Step: run the greedy optimizer over a viewshed run's completed sites. */
export function OptimizationForm({
  viewshedRunId,
  prioritiesDatasetId = null,
}: {
  viewshedRunId: string;
  /** The project's most recently uploaded priorities raster, if any. */
  prioritiesDatasetId?: string | null;
}): React.ReactElement {
  const router = useRouter();
  const [maxSites, setMaxSites] = useState<string>("");
  const [targetCoverage, setTargetCoverage] = useState<string>("");
  const [preset, setPreset] = useState<Preset>("");
  const [useUploadedRaster, setUseUploadedRaster] = useState(false);
  const [addZone, setAddZone] = useState(false);
  const [zoneGeometry, setZoneGeometry] = useState<GeoJSONGeometry | null>(null);
  const [zoneWeight, setZoneWeight] = useState("3");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);

    if (addZone && !zoneGeometry) {
      setError("Draw the priority zone on the map, or turn it off.");
      return;
    }

    setSubmitting(true);
    try {
      await optimizeCoverage(viewshedRunId, {
        max_sites: maxSites.trim().length > 0 ? Number(maxSites) : null,
        target_coverage: targetCoverage.trim().length > 0 ? Number(targetCoverage) / 100 : null,
        priorities_dataset_id: useUploadedRaster ? prioritiesDatasetId : null,
        preset: useUploadedRaster || preset === "" ? null : preset,
        priority_zones:
          addZone && zoneGeometry ? [{ geometry: zoneGeometry, weight: Number(zoneWeight) }] : [],
      });
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Unexpected error running the optimizer.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <p className="subtitle">
        Select the Sentinel positions that maximize covered (risk-weighted) surface, from whichever
        viewsheds have completed so far.
      </p>
      <div className="form-row">
        <div className="form-field">
          <label htmlFor="max-sites">Maximum Sentinels (optional)</label>
          <input
            id="max-sites"
            type="number"
            min={1}
            max={10000}
            value={maxSites}
            onChange={(event) => setMaxSites(event.target.value)}
            placeholder="unlimited"
          />
        </div>
        <div className="form-field">
          <label htmlFor="target-coverage">Target coverage % (optional)</label>
          <input
            id="target-coverage"
            type="number"
            min={1}
            max={100}
            value={targetCoverage}
            onChange={(event) => setTargetCoverage(event.target.value)}
            placeholder="none"
          />
        </div>
      </div>

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="weight-preset">Risk weighting preset</label>
          <select
            id="weight-preset"
            value={preset}
            disabled={useUploadedRaster}
            onChange={(event) => setPreset(event.target.value as Preset)}
          >
            <option value="">Uniform (every cell counts equally)</option>
            <option value="ridge_priority">Ridge priority (favour higher ground)</option>
            <option value="valley_priority">Valley priority (favour lower ground)</option>
          </select>
        </div>
        {prioritiesDatasetId ? (
          <div className="form-field">
            <label htmlFor="use-uploaded-raster">
              <input
                id="use-uploaded-raster"
                type="checkbox"
                checked={useUploadedRaster}
                onChange={(event) => setUseUploadedRaster(event.target.checked)}
              />{" "}
              Use uploaded risk raster instead
            </label>
          </div>
        ) : null}
      </div>

      <div className="form-field">
        <label htmlFor="add-zone">
          <input
            id="add-zone"
            type="checkbox"
            checked={addZone}
            onChange={(event) => setAddZone(event.target.checked)}
          />{" "}
          Boost one zone&apos;s weight
        </label>
      </div>
      {addZone ? (
        <>
          <p className="subtitle">Draw the zone to boost, then set its weight multiplier.</p>
          <InteractiveMap mode="draw" onAreaChange={setZoneGeometry} height={300} />
          <div className="form-field">
            <label htmlFor="zone-weight">Zone weight multiplier</label>
            <input
              id="zone-weight"
              type="number"
              min={0.01}
              max={100}
              step={0.5}
              value={zoneWeight}
              onChange={(event) => setZoneWeight(event.target.value)}
            />
          </div>
        </>
      ) : null}

      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? "Optimizing…" : "Run optimizer"}
      </button>
    </form>
  );
}
