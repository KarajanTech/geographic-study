"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, uploadPriorities } from "@/lib/api-client";

/** Optional step: upload a risk/priority raster, aligned to the analysis DEM. */
export function PrioritiesUploadForm({ projectId }: { projectId: string }): React.ReactElement {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
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
      await uploadPriorities(projectId, file);
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Unexpected error ingesting the raster.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <p className="subtitle">
        Upload a risk or priority raster (higher values matter more). It is resampled onto the
        analysis DEM&apos;s exact grid, so its cells line up with every viewshed.
      </p>
      <div className="form-field">
        <label htmlFor="priorities-file">GeoTIFF risk raster</label>
        <input
          id="priorities-file"
          type="file"
          accept=".tif,.tiff,image/tiff"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          required
        />
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? "Uploading…" : "Upload risk raster"}
      </button>
    </form>
  );
}
