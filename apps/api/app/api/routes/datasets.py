"""Dataset endpoints: upload, inspect, validate and preview."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import SessionDep, SettingsDep
from app.api.serializers import serialize_dataset, serialize_validation
from app.core.errors import InvalidInputError
from app.db.models import DatasetRole
from app.geo.raster import describe_raster
from app.geo.validation import validate_dem
from app.schemas.dataset import (
    DatasetListResponse,
    DatasetResponse,
    DemIngestionResponse,
    PrioritiesIngestionResponse,
    ValidationResponse,
)
from app.schemas.geojson import BoundsWGS84
from app.services import datasets as dataset_service
from app.services import priorities as priorities_service
from app.services import projects as project_service
from app.services.ingestion import DEFAULT_BUFFER_M, IngestionParameters

router = APIRouter(tags=["datasets"])

PreviewKind = Literal["preview", "hillshade_preview"]


@router.post(
    "/projects/{project_id}/datasets",
    response_model=DemIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a DEM and build the analysis surface",
)
def upload_dem(
    project_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="GeoTIFF elevation model.")],
    buffer_m: Annotated[float, Form(description="Clip buffer in metres.")] = DEFAULT_BUFFER_M,
    target_resolution_m: Annotated[
        float | None, Form(description="Resample to this cell size in metres.")
    ] = None,
) -> DemIngestionResponse:
    """Ingest a DEM: validate, reproject, clip to the study area plus buffer, shade.

    The uploaded file is stored untouched; every product is derived from it.
    """
    project = project_service.get_project(session, project_id)
    if file.filename is None:
        msg = "The uploaded file has no filename"
        raise InvalidInputError(msg)

    raw, processed = dataset_service.ingest_dem_upload(
        session,
        project,
        upload=file.file,
        filename=file.filename,
        content_type=file.content_type,
        settings=settings,
        parameters=IngestionParameters(buffer_m=buffer_m, target_resolution_m=target_resolution_m),
    )

    validation = raw.metadata_json.get("validation", {})
    bounds = processed.metadata_json.get("preview_bounds_wgs84", {})
    return DemIngestionResponse(
        raw=serialize_dataset(raw),
        processed=serialize_dataset(processed),
        validation=ValidationResponse(
            ok=bool(validation.get("ok", True)),
            errors=[],
            warnings=validation.get("warnings", []),
            coverage_ratio=validation.get("coverage_ratio"),
        ),
        preview_url=f"/api/v1/datasets/{processed.id}/hillshade_preview.png",
        preview_bounds_wgs84=BoundsWGS84(
            west=bounds["left"], south=bounds["bottom"], east=bounds["right"], north=bounds["top"]
        ),
    )


@router.post(
    "/projects/{project_id}/priorities",
    response_model=PrioritiesIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a priorities/risk raster, aligned to the analysis DEM",
)
def upload_priorities(
    project_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="GeoTIFF risk/priority raster.")],
) -> PrioritiesIngestionResponse:
    """Ingest a risk-weight raster, resampled onto the analysis DEM's exact grid.

    Requires a processed DEM to already exist for the project — there is
    nothing to align to otherwise. The raw upload is stored untouched, like
    every other raw dataset.
    """
    project = project_service.get_project(session, project_id)
    if file.filename is None:
        msg = "The uploaded file has no filename"
        raise InvalidInputError(msg)

    analysis_dataset = dataset_service.get_active_dem_dataset(session, project_id)
    if analysis_dataset is None:
        msg = "Upload a DEM for this project before uploading a priorities raster"
        raise InvalidInputError(msg, details={"project_id": str(project_id)})

    raw, processed = priorities_service.ingest_priorities_upload(
        session,
        project,
        upload=file.file,
        filename=file.filename,
        content_type=file.content_type,
        settings=settings,
        analysis_dataset=analysis_dataset,
    )

    bounds = processed.metadata_json.get("preview_bounds_wgs84", {})
    return PrioritiesIngestionResponse(
        raw=serialize_dataset(raw),
        processed=serialize_dataset(processed),
        preview_url=f"/api/v1/datasets/{processed.id}/preview.png",
        preview_bounds_wgs84=BoundsWGS84(
            west=bounds["left"], south=bounds["bottom"], east=bounds["right"], north=bounds["top"]
        ),
    )


@router.get(
    "/projects/{project_id}/datasets",
    response_model=DatasetListResponse,
    summary="List the datasets of a project",
)
def list_datasets(
    project_id: uuid.UUID,
    session: SessionDep,
    role: DatasetRole | None = None,
) -> DatasetListResponse:
    project_service.get_project(session, project_id)
    items = dataset_service.list_datasets(session, project_id, role=role)
    return DatasetListResponse(items=[serialize_dataset(d) for d in items], total=len(items))


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse, summary="Get a dataset")
def get_dataset(dataset_id: uuid.UUID, session: SessionDep) -> DatasetResponse:
    return serialize_dataset(dataset_service.get_dataset(session, dataset_id))


@router.post(
    "/datasets/{dataset_id}/validate",
    response_model=ValidationResponse,
    summary="Re-validate a dataset against its study area",
)
def validate_dataset(
    dataset_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> ValidationResponse:
    """Re-read the file from storage and re-run every validation rule."""
    dataset = dataset_service.get_dataset(session, dataset_id)
    project = project_service.get_project(session, dataset.project_id)
    path = dataset_service.dataset_file(dataset, settings)
    metadata = describe_raster(path)
    report = validate_dem(metadata, project_service.project_study_area(project))
    return serialize_validation(report)


@router.get(
    "/datasets/{dataset_id}/{kind}.png",
    response_class=FileResponse,
    summary="Download a dataset preview image",
    responses={200: {"content": {"image/png": {}}}},
)
def get_preview(
    dataset_id: uuid.UUID, kind: PreviewKind, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    """Serve the greyscale PNG preview or its hillshade version.

    A preview is a display artefact; measurements come from the API, never from
    the image.
    """
    dataset = dataset_service.get_dataset(session, dataset_id)
    path = dataset_service.dataset_file(dataset, settings, key=kind)
    return FileResponse(path, media_type="image/png", filename=f"{dataset_id}_{kind}.png")


@router.get(
    "/datasets/{dataset_id}/download.tif",
    response_class=FileResponse,
    summary="Download the dataset GeoTIFF",
    responses={200: {"content": {"image/tiff": {}}}},
)
def download_dataset(
    dataset_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    dataset = dataset_service.get_dataset(session, dataset_id)
    path = dataset_service.dataset_file(dataset, settings)
    return FileResponse(path, media_type="image/tiff", filename=path.name)
