"""Priority/risk raster ingestion.

A priorities raster expresses which cells matter more for coverage — the
"riesgo" ``ROADMAP.md`` Phase 6 asks the optimizer to weight. Unlike the DEM
pipeline, it is not clipped with its own buffer or reprojected to a
freshly-derived grid: it is snapped onto the project's existing analysis DEM's
*exact* grid (see :func:`app.geo.warp.resample_to_reference`), so every cell
of the aligned raster corresponds 1:1, by array index, to a cell of the
surface the optimizer already builds its candidate-cell matrix over.
"""

from __future__ import annotations

import uuid
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Dataset, DatasetRole, DatasetStatus, DatasetType, Project
from app.geo.preview import write_png_preview
from app.geo.raster import describe_raster, metadata_to_storage_dict
from app.geo.warp import resample_to_reference
from app.services.datasets import apply_raster_metadata, dataset_file, list_datasets
from app.services.storage import (
    processed_dataset_dir,
    raw_dataset_dir,
    safe_filename,
    store_upload,
    to_relative_uri,
    validate_raster_upload,
)

ALIGNED_NAME = "priorities_aligned.tif"
PREVIEW_NAME = "preview.png"


def get_active_priorities_dataset(session: Session, project_id: uuid.UUID) -> Dataset | None:
    """The project's most recently ingested, ready priorities raster, if any."""
    candidates = [
        dataset
        for dataset in list_datasets(session, project_id, role=DatasetRole.PROCESSED)
        if dataset.dataset_type is DatasetType.PRIORITIES and dataset.status is DatasetStatus.READY
    ]
    return candidates[-1] if candidates else None


def ingest_priorities_upload(
    session: Session,
    project: Project,
    *,
    upload: BinaryIO,
    filename: str,
    content_type: str | None,
    settings: Settings,
    analysis_dataset: Dataset,
) -> tuple[Dataset, Dataset]:
    """Store an uploaded priorities raster, aligned to the project's analysis DEM.

    Args:
        analysis_dataset: The project's processed DEM — the ``upload_dem``
            endpoint's ``processed`` dataset. Its exact grid is what the
            uploaded raster is resampled onto.

    Returns the (raw, processed) dataset pair, matching ``ingest_dem_upload``.

    Raises:
        InvalidInputError: if the upload is not a GeoTIFF, has no CRS, or the
            analysis dataset it must align to is missing from storage.
    """
    validate_raster_upload(filename, content_type)

    raw_dataset = Dataset(
        project_id=project.id,
        dataset_type=DatasetType.PRIORITIES,
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
        dataset_type=DatasetType.PRIORITIES,
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

    reference_path = dataset_file(analysis_dataset, settings)
    output_dir = processed_dataset_dir(project.id, processed_dataset.id, settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    aligned_path = output_dir / ALIGNED_NAME

    try:
        aligned = resample_to_reference(stored.path, aligned_path, reference_path)
    except Exception as error:
        message = getattr(error, "message", str(error))
        raw_dataset.status = DatasetStatus.FAILED
        raw_dataset.error = message
        processed_dataset.status = DatasetStatus.FAILED
        processed_dataset.error = message
        session.flush()
        raise

    source_metadata = describe_raster(stored.path)
    apply_raster_metadata(raw_dataset, source_metadata)
    raw_dataset.status = DatasetStatus.READY
    raw_dataset.metadata_json = {**metadata_to_storage_dict(source_metadata), "source": "upload"}

    preview = write_png_preview(aligned_path, output_dir / PREVIEW_NAME)

    aligned_metadata = describe_raster(aligned_path)
    apply_raster_metadata(processed_dataset, aligned_metadata)
    processed_dataset.status = DatasetStatus.READY
    processed_dataset.source_uri = to_relative_uri(aligned.path, settings)
    processed_dataset.metadata_json = {
        **metadata_to_storage_dict(aligned_metadata),
        "aligned_to_dataset_id": str(analysis_dataset.id),
        "derived_files": {"preview": to_relative_uri(preview.path, settings)},
        "preview_bounds_wgs84": {
            "left": preview.bounds_wgs84.left,
            "bottom": preview.bounds_wgs84.bottom,
            "right": preview.bounds_wgs84.right,
            "top": preview.bounds_wgs84.top,
        },
    }
    processed_dataset.processing_history = [
        {"step": "align_to_reference", "reference_dataset_id": str(analysis_dataset.id)},
        {"step": "preview", "size_px": [preview.width, preview.height]},
    ]
    session.flush()

    return raw_dataset, processed_dataset


__all__ = ["get_active_priorities_dataset", "ingest_priorities_upload"]
