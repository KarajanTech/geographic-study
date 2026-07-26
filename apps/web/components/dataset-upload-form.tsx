"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, uploadDataset } from "@/lib/api-client";

/** Step: ingest a GeoTIFF DEM for a project that has none yet. */
export function DatasetUploadForm({ projectId }: { projectId: string }): React.ReactElement {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [bufferM, setBufferM] = useState(2000);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);

    if (!file) {
      setError("Choose a GeoTIFF file.");
      return;
    }

    setSubmitting(true);
    try {
      await uploadDataset(projectId, file, bufferM);
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Unexpected error ingesting the DEM.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <p className="subtitle">
        Upload a GeoTIFF elevation model. It is validated, reprojected to the project&apos;s
        analysis CRS, and clipped to the study area with a buffer.
      </p>
      <div className="form-row">
        <div className="form-field">
          <label htmlFor="dem-file">GeoTIFF DEM</label>
          <input
            id="dem-file"
            type="file"
            accept=".tif,.tiff,image/tiff"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </div>
        <div className="form-field">
          <label htmlFor="buffer-m">Buffer around the study area (m)</label>
          <input
            id="buffer-m"
            type="number"
            min={0}
            max={50000}
            step={100}
            value={bufferM}
            onChange={(event) => setBufferM(Number(event.target.value))}
          />
        </div>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? "Ingesting…" : "Upload DEM"}
      </button>
    </form>
  );
}
