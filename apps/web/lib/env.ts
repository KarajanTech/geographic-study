/**
 * Frontend configuration.
 *
 * Base URLs come from the environment. Server components talk to the API over
 * the internal network (`API_BASE_URL`), browsers use the public one
 * (`NEXT_PUBLIC_API_BASE_URL`).
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

function trimTrailingSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

/** Base URL to call from a server component or route handler. */
export function serverApiBaseUrl(): string {
  return trimTrailingSlash(
    process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  );
}

/** Base URL to call from the browser. */
export function browserApiBaseUrl(): string {
  return trimTrailingSlash(process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL);
}

/** Path prefix of the versioned API. */
export const API_V1_PREFIX = "/api/v1";
