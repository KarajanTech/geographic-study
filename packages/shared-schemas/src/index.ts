/**
 * Types shared between the API and the web app.
 *
 * `src/generated/api.ts` is generated from `openapi.json`, which is exported
 * from the FastAPI application. Do not edit either by hand: run
 * `make schemas` after changing an API schema.
 */
import type { components, paths } from "./generated/api";

export type { components, paths };

/** Liveness payload returned by `GET /api/v1/health`. */
export type HealthResponse = components["schemas"]["HealthResponse"];

/** Readiness payload returned by `GET /api/v1/health/ready`. */
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];

/** Status of a single external dependency. */
export type ComponentStatus = components["schemas"]["ComponentStatus"];

/** A study area plus the projected metric CRS every calculation uses. */
export type Project = components["schemas"]["ProjectResponse"];
export type ProjectList = components["schemas"]["ProjectListResponse"];
export type ProjectCreateRequest = components["schemas"]["ProjectCreateRequest"];

/** A stored raster with its full geospatial description. */
export type Dataset = components["schemas"]["DatasetResponse"];
export type DatasetList = components["schemas"]["DatasetListResponse"];
export type DatasetRole = components["schemas"]["DatasetRole"];
export type DatasetStatus = components["schemas"]["DatasetStatus"];
export type DatasetType = components["schemas"]["DatasetType"];

/** The raw upload and the analysis surface derived from it. */
export type DemIngestion = components["schemas"]["DemIngestionResponse"];
export type ValidationResult = components["schemas"]["ValidationResponse"];

/** The raw upload and the priorities raster aligned to the analysis DEM. */
export type PrioritiesIngestion = components["schemas"]["PrioritiesIngestionResponse"];

/** Extent in EPSG:4326, used to place a preview image on a map. */
export type BoundsWGS84 = components["schemas"]["BoundsWGS84"];
/** Extent in a projected CRS, with its units named. */
export type BoundsMetric = components["schemas"]["BoundsMetric"];
/** A GeoJSON Polygon or MultiPolygon in EPSG:4326. */
export type GeoJSONGeometry = components["schemas"]["GeoJSONGeometry"];
/** A GeoJSON Point in EPSG:4326. */
export type GeoJSONPoint = components["schemas"]["GeoJSONPoint"];

/** One execution of a pipeline stage, with its parameters and metrics. */
export type AnalysisRun = components["schemas"]["AnalysisRunResponse"];
export type AnalysisRunList = components["schemas"]["AnalysisRunListResponse"];
export type AnalysisRunKind = components["schemas"]["AnalysisRunKind"];
export type AnalysisRunStatus = components["schemas"]["AnalysisRunStatus"];

/** Parameters for a candidate generation run. */
export type CandidateGenerationRequest = components["schemas"]["CandidateGenerationRequest"];

/** One potential Sentinel location produced by a candidate run. */
export type CandidateSite = components["schemas"]["CandidateSiteResponse"];
export type CandidateList = components["schemas"]["CandidateListResponse"];

/** Parameters for a batch viewshed computation over a candidate run. */
export type ViewshedRunRequest = components["schemas"]["ViewshedRunRequest"];

/** A computed visibility mask for one candidate site. */
export type Viewshed = components["schemas"]["ViewshedResponse"];
export type ViewshedList = components["schemas"]["ViewshedListResponse"];
export type ViewshedStatus = components["schemas"]["ViewshedStatus"];

/** Parameters for a greedy coverage-maximization run. */
export type OptimizationRunRequest = components["schemas"]["OptimizationRunRequest"];
/** A zone whose cells get an extra weight multiplier. */
export type PriorityZoneRequest = components["schemas"]["PriorityZoneRequest"];

/** The Sentinel positions a greedy run selected, and how it got there. */
export type OptimizationSolution = components["schemas"]["OptimizationSolutionResponse"];
export type OptimizationSolutionList = components["schemas"]["OptimizationSolutionListResponse"];
export type OptimizationIteration = components["schemas"]["OptimizationIteration"];

/** Error document rendered by the API for every domain error. */
export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}
