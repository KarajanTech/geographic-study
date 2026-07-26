"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { GeoJSONGeometry } from "@sentinel/shared-schemas";

import { ApiError, createProject } from "@/lib/api-client";

import { InteractiveMap } from "./interactive-map-loader";

/** Step one of the Phase 5 flow: name the project and draw its study area. */
export function ProjectForm(): React.ReactElement {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [area, setArea] = useState<GeoJSONGeometry | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);

    if (name.trim().length === 0) {
      setError("Give the project a name.");
      return;
    }
    if (!area) {
      setError("Draw the study area boundary on the map before continuing.");
      return;
    }

    setSubmitting(true);
    try {
      const project = await createProject({
        name: name.trim(),
        description: description.trim().length > 0 ? description.trim() : null,
        area,
      });
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Unexpected error creating the project.",
      );
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="panel">
      <h2>1. Name the project</h2>
      <div className="form-field">
        <label htmlFor="project-name">Name</label>
        <input
          id="project-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={200}
          required
        />
      </div>
      <div className="form-field">
        <label htmlFor="project-description">Description (optional)</label>
        <textarea
          id="project-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={2000}
          rows={2}
        />
      </div>

      <h2>2. Draw the study area</h2>
      <p className="subtitle">
        Outline the area a Sentinel network should cover. One polygon; use the edit tool on the map
        to adjust it.
      </p>
      <InteractiveMap mode="draw" onAreaChange={setArea} height={420} />

      {error ? <p className="form-error">{error}</p> : null}

      <button type="submit" disabled={submitting}>
        {submitting ? "Creating…" : "Create project"}
      </button>
    </form>
  );
}
