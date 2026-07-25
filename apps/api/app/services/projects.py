"""Project persistence.

Thin layer between the HTTP routes and the database: it validates the study
area through :mod:`app.geo.area` and stores the result. No geospatial logic
lives here.
"""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ResourceNotFoundError
from app.db.models import STORAGE_SRID, Project
from app.geo.area import StudyArea, parse_study_area


def create_project(
    session: Session,
    *,
    name: str,
    area_geojson: dict[str, Any],
    description: str | None = None,
    analysis_crs: str | None = None,
) -> Project:
    """Validate the study area and persist a new project."""
    study_area = parse_study_area(area_geojson, analysis_crs=analysis_crs)

    project = Project(
        name=name,
        description=description,
        area_geometry=from_shape(study_area.geometry, srid=STORAGE_SRID),
        analysis_crs=study_area.analysis_crs,
        area_km2=study_area.area_km2,
        centroid_lon=study_area.centroid_lon,
        centroid_lat=study_area.centroid_lat,
    )
    session.add(project)
    session.flush()
    return project


def get_project(session: Session, project_id: uuid.UUID) -> Project:
    """Fetch a project or raise :class:`ResourceNotFoundError`."""
    project = session.get(Project, project_id)
    if project is None:
        msg = "Project not found"
        raise ResourceNotFoundError(msg, details={"project_id": str(project_id)})
    return project


def list_projects(session: Session, *, limit: int = 50, offset: int = 0) -> list[Project]:
    statement = select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
    return list(session.scalars(statement))


def update_project(
    session: Session,
    project_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    """Update descriptive fields only.

    The study area and the analysis CRS are immutable: datasets have already
    been reprojected and clipped against them, so changing either would
    silently invalidate every derived product.
    """
    project = get_project(session, project_id)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    session.flush()
    return project


def project_area_geojson(project: Project) -> dict[str, Any]:
    """The stored study area as a GeoJSON geometry in EPSG:4326."""
    return dict(mapping(to_shape(project.area_geometry)))


def project_study_area(project: Project) -> StudyArea:
    """Rebuild the validated study area from a stored project."""
    return parse_study_area(project_area_geojson(project), analysis_crs=project.analysis_crs)
