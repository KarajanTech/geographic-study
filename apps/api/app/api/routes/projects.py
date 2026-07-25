"""Project endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.api.serializers import serialize_project
from app.core.logging import get_logger
from app.db.models import Project
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.services import projects as project_service

router = APIRouter(prefix="/projects", tags=["projects"])

_log = get_logger(__name__)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project from a study area",
)
def create_project(payload: ProjectCreateRequest, session: SessionDep) -> ProjectResponse:
    """Validate the study area, choose the analysis CRS and store the project."""
    project = project_service.create_project(
        session,
        name=payload.name,
        description=payload.description,
        area_geojson=payload.area.to_dict(),
        analysis_crs=payload.analysis_crs,
    )
    _log.info(
        "project_created",
        project_id=str(project.id),
        analysis_crs=project.analysis_crs,
        area_km2=round(project.area_km2, 3),
    )
    return serialize_project(project, dataset_count=0)


@router.get("", response_model=ProjectListResponse, summary="List projects")
def list_projects(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    items = project_service.list_projects(session, limit=limit, offset=offset)
    total = session.scalar(select(func.count()).select_from(Project)) or 0
    return ProjectListResponse(items=[serialize_project(p) for p in items], total=total)


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get a project")
def get_project(project_id: uuid.UUID, session: SessionDep) -> ProjectResponse:
    return serialize_project(project_service.get_project(session, project_id))


@router.patch("/{project_id}", response_model=ProjectResponse, summary="Rename a project")
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdateRequest, session: SessionDep
) -> ProjectResponse:
    """Update name and description.

    The study area and analysis CRS cannot change: datasets have already been
    reprojected and clipped against them.
    """
    project = project_service.update_project(
        session, project_id, name=payload.name, description=payload.description
    )
    return serialize_project(project)
