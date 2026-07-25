"""Dataset persistence and ingestion orchestration.

This is where storage, the ingestion pipeline and the database meet. The
geospatial work itself lives in :mod:`app.services.ingestion`; here we only
decide what is written where, and record provenance.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, BinaryIO

from geoalchemy2.shape import from_shape
from shapely.geometry import box
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import InvalidInputError, ResourceNotFoundError
from app.core.logging import get_logger
from app.db.models import STORAGE_SRID, Dataset, DatasetRole, DatasetStatus, DatasetType, Project
from app.geo.area import reproject_geometry
from app.geo.crs import WGS84
from app.geo.raster import RasterMetadata, metadata_to_storage_dict
from app.services.ingestion import IngestionParameters, ingest_dem
from app.services.projects import project_study_area
from app.services.storage import (
    from_relative_uri,
    processed_dataset_dir,
    raw_dataset_dir,
    safe_filename,
    store_upload,
    to_relative_uri,
    validate_raster_upload,
)

_log = get_logger(__name__)


def get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        msg = "Dataset not found"
        raise ResourceNotFoundError(msg, details={"dataset_id": str(dataset_id)})
    return dataset


def list_datasets(
    session: Session, project_id: uuid.UUID, *, role: DatasetRole | None = None
) -> list[Dataset]:
    statement = select(Dataset).where(Dataset.project_id == project_id)
    if role is not None:
        statement = statement.where(Dataset.role == role)
    return list(session.scalars(statement.order_by(Dataset.created_at)))


def _footprint_wgs84(metadata: RasterMetadata) -> Any | None:
    """Store the raster extent as a WGS84 polygon, for map display only."""
    if metadata.crs is None:
        return None
    footprint = reproject_geometry(box(*metadata.bounds.as_tuple()), metadata.crs, WGS84)
    return from_shape(footprint, srid=STORAGE_SRID)


def _apply_metadata(dataset: Dataset, metadata: RasterMetadata) -> None:
    dataset.crs = metadata.crs
    dataset.units = metadata.units
    dataset.resolution_x = metadata.resolution_x
    dataset.resolution_y = metadata.resolution_y
    dataset.nodata = metadata.nodata
    dataset.bounds_left = metadata.bounds.left
    dataset.bounds_bottom = metadata.bounds.bottom
    dataset.bounds_right = metadata.bounds.right
    dataset.bounds_top = metadata.bounds.top
    dataset.footprint = _footprint_wgs84(metadata)
    dataset.checksum_sha256 = metadata.checksum_sha256
    dataset.size_bytes = metadata.size_bytes


def ingest_dem_upload(
    session: Session,
    project: Project,
    *,
    upload: BinaryIO,
    filename: str,
    content_type: str | None,
    settings: Settings,
    parameters: IngestionParameters | None = None,
) -> tuple[Dataset, Dataset]:
    """Store an uploaded DEM and produce the analysis-ready surface.

    Returns the (raw, processed) dataset pair. On failure the raw dataset is
    kept with ``status=failed`` and the error message: the upload itself is
    still valid provenance, and the operator needs to see why it was rejected.

    Phase 1 runs this synchronously. It is deliberately free of HTTP and
    session-lifecycle assumptions so Phase 3 can hand it to a worker.
    """
    validate_raster_upload(filename, content_type)

    raw_dataset = Dataset(
        project_id=project.id,
        dataset_type=DatasetType.DEM,
        role=DatasetRole.RAW,
        status=DatasetStatus.PENDING,
        source_uri="",
        original_filename=filename,
        checksum_sha256="",
        size_bytes=0,
        metadata_json={},
        processing_history=[],
    )
    session.add(raw_dataset)
    session.flush()

    raw_dir = raw_dataset_dir(project.id, raw_dataset.id, settings)
    raw_path = raw_dir / safe_filename(filename)
    stored = store_upload(upload, raw_path, max_bytes=settings.max_upload_bytes)

    raw_dataset.source_uri = to_relative_uri(stored.path, settings)
    raw_dataset.checksum_sha256 = stored.checksum_sha256
    raw_dataset.size_bytes = stored.size_bytes
    raw_dataset.status = DatasetStatus.PROCESSING
    session.flush()

    processed_dataset = Dataset(
        project_id=project.id,
        derived_from_id=raw_dataset.id,
        dataset_type=DatasetType.DEM,
        role=DatasetRole.PROCESSED,
        status=DatasetStatus.PROCESSING,
        source_uri="",
        original_filename=None,
        checksum_sha256="",
        size_bytes=0,
        metadata_json={},
        processing_history=[],
    )
    session.add(processed_dataset)
    session.flush()

    study_area = project_study_area(project)
    output_dir = processed_dataset_dir(project.id, processed_dataset.id, settings)

    try:
        result = ingest_dem(stored.path, output_dir, study_area, parameters)
    except Exception as error:
        message = getattr(error, "message", str(error))
        raw_dataset.status = DatasetStatus.FAILED
        raw_dataset.error = message
        processed_dataset.status = DatasetStatus.FAILED
        processed_dataset.error = message
        # Keep whatever metadata could be read: a rejected file still tells the
        # operator what was wrong with it.
        _apply_raw_metadata_best_effort(raw_dataset, stored.path)
        session.flush()
        _log.warning(
            "dem_ingestion_failed",
            project_id=str(project.id),
            dataset_id=str(raw_dataset.id),
            error=message,
        )
        raise

    _apply_metadata(raw_dataset, result.source_metadata)
    raw_dataset.status = DatasetStatus.READY
    raw_dataset.metadata_json = {
        **metadata_to_storage_dict(result.source_metadata),
        "source": "upload",
        "validation": {
            "ok": result.validation.ok,
            "coverage_ratio": result.validation.coverage_ratio,
            "warnings": [
                {"code": w.code, "message": w.message} for w in result.validation.warnings
            ],
        },
    }

    _apply_metadata(processed_dataset, result.analysis_metadata)
    processed_dataset.status = DatasetStatus.READY
    processed_dataset.source_uri = to_relative_uri(result.analysis_dem.path, settings)
    processed_dataset.metadata_json = {
        **metadata_to_storage_dict(result.analysis_metadata),
        "analysis_crs": project.analysis_crs,
        "parameters": result.parameters.as_dict(),
        "valid_cell_count": result.analysis_dem.valid_cell_count,
        "total_cell_count": result.analysis_dem.total_cell_count,
        "valid_ratio": result.analysis_dem.valid_ratio,
        "runtime_seconds": result.runtime_seconds,
        "derived_files": {
            "hillshade": to_relative_uri(result.hillshade_path, settings),
            "preview": to_relative_uri(result.preview.path, settings),
            "hillshade_preview": to_relative_uri(result.hillshade_preview.path, settings),
        },
        "preview_bounds_wgs84": result.preview.bounds_wgs84.model_dump(),
    }
    processed_dataset.processing_history = result.processing_history
    session.flush()

    return raw_dataset, processed_dataset


def _apply_raw_metadata_best_effort(dataset: Dataset, path: Path) -> None:
    from app.geo.raster import describe_raster

    try:
        metadata = describe_raster(path)
    except InvalidInputError:
        return
    _apply_metadata(dataset, metadata)
    dataset.metadata_json = {**metadata_to_storage_dict(metadata), "source": "upload"}


def dataset_file(dataset: Dataset, settings: Settings, key: str | None = None) -> Path:
    """Resolve a dataset file on disk.

    Args:
        key: ``None`` for the dataset itself, or a key from ``derived_files``
            (``hillshade``, ``preview``, ``hillshade_preview``).
    """
    if key is None:
        uri = dataset.source_uri
    else:
        derived = dataset.metadata_json.get("derived_files", {})
        uri = derived.get(key, "")
        if not uri:
            msg = f"Dataset has no {key} product"
            raise ResourceNotFoundError(msg, details={"dataset_id": str(dataset.id), "key": key})

    path = from_relative_uri(uri, settings)
    if not path.is_file():
        msg = "Dataset file is missing from storage"
        raise ResourceNotFoundError(msg, details={"dataset_id": str(dataset.id), "uri": uri})
    return path
