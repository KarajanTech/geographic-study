/**
 * Typed client for the Sentinel Planner API.
 *
 * Every response type comes from `@sentinel/shared-schemas`, which is generated
 * from the API's OpenAPI document. Components never call `fetch` directly and
 * never perform geospatial computation: they render what the API returns.
 */
import type {
  ApiErrorPayload,
  Dataset,
  DatasetList,
  HealthResponse,
  Project,
  ProjectList,
  ReadinessResponse,
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

async function request<T>(path: string, options: ApiClientOptions = {}): Promise<T> {
  const url = `${resolveBaseUrl(options.baseUrl)}${API_V1_PREFIX}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
      // Health data is live state, never a cached page artefact.
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

/** `GET /api/v1/projects/{id}/datasets`. */
export function listProjectDatasets(id: string, options?: ApiClientOptions): Promise<DatasetList> {
  return request<DatasetList>(`/projects/${encodeURIComponent(id)}/datasets`, options);
}

/** `GET /api/v1/datasets/{id}`. */
export function getDataset(id: string, options?: ApiClientOptions): Promise<Dataset> {
  return request<Dataset>(`/datasets/${encodeURIComponent(id)}`, options);
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
