/**
 * Typed client for the Sentinel Planner API.
 *
 * Every response type comes from `@sentinel/shared-schemas`, which is generated
 * from the API's OpenAPI document. Components never call `fetch` directly and
 * never perform geospatial computation: they render what the API returns.
 */
import type {
  AnalysisRun,
  AnalysisRunList,
  ApiErrorPayload,
  CandidateGenerationRequest,
  CandidateList,
  Dataset,
  DatasetList,
  DemIngestion,
  HealthResponse,
  OptimizationRunRequest,
  OptimizationSolution,
  OptimizationSolutionList,
  PrioritiesIngestion,
  Project,
  ProjectCreateRequest,
  ProjectList,
  ReadinessResponse,
  ViewshedList,
  ViewshedRunRequest,
} from "@sentinel/shared-schemas";

import { API_V1_PREFIX, browserApiBaseUrl, serverApiBaseUrl } from "./env";

/** Error raised for any non-2xx API response or transport failure. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    status: number,
    code: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function isApiErrorPayload(value: unknown): value is ApiErrorPayload {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const { error } = value as { error: unknown };
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}

export interface ApiClientOptions {
  /** Override the base URL; defaults to the server or browser environment value. */
  baseUrl?: string;
  /** Abort the request after this many milliseconds. */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 10_000;

function resolveBaseUrl(explicit?: string): string {
  if (explicit !== undefined) {
    return explicit;
  }
  return typeof window === "undefined" ? serverApiBaseUrl() : browserApiBaseUrl();
}

interface RequestOptions extends ApiClientOptions {
  method?: "GET" | "POST";
  jsonBody?: unknown;
  /** Multipart body, e.g. a file upload. Mutually exclusive with `jsonBody`. */
  formBody?: FormData;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = `${resolveBaseUrl(options.baseUrl)}${API_V1_PREFIX}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      // The browser sets its own multipart Content-Type (with boundary) when
      // the body is a FormData instance — setting it manually breaks the upload.
      headers:
        options.jsonBody !== undefined
          ? { Accept: "application/json", "Content-Type": "application/json" }
          : { Accept: "application/json" },
      body:
        options.formBody ??
        (options.jsonBody !== undefined ? JSON.stringify(options.jsonBody) : undefined),
      signal: controller.signal,
      // Live state, never a cached page artefact.
      cache: "no-store",
    });
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : "unknown transport error";
    throw new ApiError(`Could not reach the API at ${url}: ${reason}`, 0, "network_error");
  } finally {
    clearTimeout(timeout);
  }

  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (isApiErrorPayload(body)) {
      throw new ApiError(body.error.message, response.status, body.error.code, body.error.details);
    }
    throw new ApiError(`API returned ${response.status}`, response.status, "http_error");
  }

  return body as T;
}

/** `GET /api/v1/health` — liveness. */
export function getHealth(options?: ApiClientOptions): Promise<HealthResponse> {
  return request<HealthResponse>("/health", options);
}

/**
 * `GET /api/v1/health/ready` — readiness.
 *
 * A 503 is a valid, informative answer here, so the payload is returned
 * together with the readiness flag instead of raising.
 */
export async function getReadiness(
  options: ApiClientOptions = {},
): Promise<{ ready: boolean; payload: ReadinessResponse }> {
  const url = `${resolveBaseUrl(options.baseUrl)}${API_V1_PREFIX}/health/ready`;
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
      cache: "no-store",
    });
    const payload = (await response.json()) as ReadinessResponse;
    return { ready: response.ok, payload };
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : "unknown transport error";
    throw new ApiError(`Could not reach the API at ${url}: ${reason}`, 0, "network_error");
  } finally {
    clearTimeout(timeout);
  }
}

/** `GET /api/v1/projects` — study areas, newest first. */
export function listProjects(options?: ApiClientOptions): Promise<ProjectList> {
  return request<ProjectList>("/projects", options);
}

/** `GET /api/v1/projects/{id}`. */
export function getProject(id: string, options?: ApiClientOptions): Promise<Project> {
  return request<Project>(`/projects/${encodeURIComponent(id)}`, options);
}

/** `POST /api/v1/projects` — create a study area from a drawn or uploaded polygon. */
export function createProject(
  payload: ProjectCreateRequest,
  options?: ApiClientOptions,
): Promise<Project> {
  return request<Project>("/projects", { ...options, method: "POST", jsonBody: payload });
}

/** `GET /api/v1/projects/{id}/datasets`. */
export function listProjectDatasets(id: string, options?: ApiClientOptions): Promise<DatasetList> {
  return request<DatasetList>(`/projects/${encodeURIComponent(id)}/datasets`, options);
}

const UPLOAD_TIMEOUT_MS = 120_000;

/**
 * `POST /api/v1/projects/{id}/datasets` — ingest a DEM: validate, reproject to
 * the project's analysis CRS, clip with a buffer, derive a hillshade preview.
 */
export function uploadDataset(
  projectId: string,
  file: File,
  bufferM: number,
  targetResolutionM: number | null = null,
  options?: ApiClientOptions,
): Promise<DemIngestion> {
  const formBody = new FormData();
  formBody.set("file", file);
  formBody.set("buffer_m", String(bufferM));
  if (targetResolutionM !== null) {
    formBody.set("target_resolution_m", String(targetResolutionM));
  }
  return request<DemIngestion>(`/projects/${encodeURIComponent(projectId)}/datasets`, {
    ...options,
    method: "POST",
    formBody,
    timeoutMs: options?.timeoutMs ?? UPLOAD_TIMEOUT_MS,
  });
}

/** `GET /api/v1/datasets/{id}`. */
export function getDataset(id: string, options?: ApiClientOptions): Promise<Dataset> {
  return request<Dataset>(`/datasets/${encodeURIComponent(id)}`, options);
}

/**
 * `POST /api/v1/projects/{id}/priorities` — ingest a risk/priority raster,
 * resampled onto the project's analysis DEM's exact grid.
 */
export function uploadPriorities(
  projectId: string,
  file: File,
  options?: ApiClientOptions,
): Promise<PrioritiesIngestion> {
  const formBody = new FormData();
  formBody.set("file", file);
  return request<PrioritiesIngestion>(`/projects/${encodeURIComponent(projectId)}/priorities`, {
    ...options,
    method: "POST",
    formBody,
    timeoutMs: options?.timeoutMs ?? UPLOAD_TIMEOUT_MS,
  });
}

/**
 * Browser URL of a dataset preview image.
 *
 * Always the public base URL: the browser, not the server, loads this.
 */
export function datasetPreviewUrl(
  datasetId: string,
  kind: "preview" | "hillshade_preview" = "hillshade_preview",
): string {
  return `${browserApiBaseUrl()}${API_V1_PREFIX}/datasets/${encodeURIComponent(datasetId)}/${kind}.png`;
}

/** Browser URL of a dataset's GeoTIFF. */
export function datasetDownloadUrl(datasetId: string): string {
  return `${browserApiBaseUrl()}${API_V1_PREFIX}/datasets/${encodeURIComponent(datasetId)}/download.tif`;
}

/** `GET /api/v1/projects/{id}/analysis-runs`. */
export function listAnalysisRuns(
  projectId: string,
  options?: ApiClientOptions,
): Promise<AnalysisRunList> {
  return request<AnalysisRunList>(
    `/projects/${encodeURIComponent(projectId)}/analysis-runs`,
    options,
  );
}

/** `GET /api/v1/analysis-runs/{id}`. */
export function getAnalysisRun(runId: string, options?: ApiClientOptions): Promise<AnalysisRun> {
  return request<AnalysisRun>(`/analysis-runs/${encodeURIComponent(runId)}`, options);
}

/** `POST /api/v1/projects/{id}/candidates` — generate and persist candidate sites. */
export function generateCandidates(
  projectId: string,
  payload: CandidateGenerationRequest,
  options?: ApiClientOptions,
): Promise<AnalysisRun> {
  return request<AnalysisRun>(`/projects/${encodeURIComponent(projectId)}/candidates`, {
    ...options,
    method: "POST",
    jsonBody: payload,
  });
}

/** `GET /api/v1/analysis-runs/{id}/candidates`. */
export function listCandidates(runId: string, options?: ApiClientOptions): Promise<CandidateList> {
  return request<CandidateList>(`/analysis-runs/${encodeURIComponent(runId)}/candidates`, options);
}

/**
 * `POST /api/v1/analysis-runs/{candidatesRunId}/viewsheds` — queue viewshed
 * computation. Returns immediately; a worker computes the results.
 */
export function enqueueViewsheds(
  candidatesRunId: string,
  payload: ViewshedRunRequest,
  options?: ApiClientOptions,
): Promise<AnalysisRun> {
  return request<AnalysisRun>(`/analysis-runs/${encodeURIComponent(candidatesRunId)}/viewsheds`, {
    ...options,
    method: "POST",
    jsonBody: payload,
  });
}

/** `GET /api/v1/analysis-runs/{id}/viewsheds` — a batch run's viewsheds and progress. */
export function listViewsheds(runId: string, options?: ApiClientOptions): Promise<ViewshedList> {
  return request<ViewshedList>(`/analysis-runs/${encodeURIComponent(runId)}/viewsheds`, options);
}

/** Browser URL of a viewshed's map-overlay preview PNG. */
export function viewshedPreviewUrl(viewshedId: string): string {
  return `${browserApiBaseUrl()}${API_V1_PREFIX}/viewsheds/${encodeURIComponent(viewshedId)}/preview.png`;
}

/** Browser URL of a viewshed's mask GeoTIFF. */
export function viewshedMaskUrl(viewshedId: string): string {
  return `${browserApiBaseUrl()}${API_V1_PREFIX}/viewsheds/${encodeURIComponent(viewshedId)}/mask.tif`;
}

/**
 * `POST /api/v1/analysis-runs/{viewshedRunId}/optimize` — greedily select
 * candidates that maximize covered surface. Runs synchronously; returns the
 * finished solution.
 */
export function optimizeCoverage(
  viewshedRunId: string,
  payload: OptimizationRunRequest,
  options?: ApiClientOptions,
): Promise<OptimizationSolution> {
  return request<OptimizationSolution>(
    `/analysis-runs/${encodeURIComponent(viewshedRunId)}/optimize`,
    { ...options, method: "POST", jsonBody: payload },
  );
}

/** `GET /api/v1/analysis-runs/{id}/optimization-solutions`. */
export function listOptimizationSolutions(
  runId: string,
  options?: ApiClientOptions,
): Promise<OptimizationSolutionList> {
  return request<OptimizationSolutionList>(
    `/analysis-runs/${encodeURIComponent(runId)}/optimization-solutions`,
    options,
  );
}

/** `GET /api/v1/optimization-solutions/{id}`. */
export function getOptimizationSolution(
  solutionId: string,
  options?: ApiClientOptions,
): Promise<OptimizationSolution> {
  return request<OptimizationSolution>(
    `/optimization-solutions/${encodeURIComponent(solutionId)}`,
    options,
  );
}

/** Browser URL to download the selected Sentinels as a GeoJSON FeatureCollection. */
export function optimizationSolutionGeoJsonUrl(solutionId: string): string {
  return `${browserApiBaseUrl()}${API_V1_PREFIX}/optimization-solutions/${encodeURIComponent(solutionId)}/export.geojson`;
}

/** Browser URL to download the selected Sentinels as CSV. */
export function optimizationSolutionCsvUrl(solutionId: string): string {
  return `${browserApiBaseUrl()}${API_V1_PREFIX}/optimization-solutions/${encodeURIComponent(solutionId)}/export.csv`;
}
