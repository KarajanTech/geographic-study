"""Shared pytest fixtures.

Tests never depend on the developer's environment: settings are built from an
isolated temporary data directory and an explicit environment. Fixtures that
need PostGIS skip themselves when no database is reachable, and run in CI.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Environment, Settings, get_settings
from app.db.session import reset_engine_cache
from app.geo.area import StudyArea, parse_study_area
from app.geo.sample_dem import SyntheticDemSpec, write_synthetic_dem
from app.main import create_app

# Synthetic terrain used across the geo tests: 8 x 8 km at 50 m in UTM 30N,
# placed over central Spain so the ETRS89 selection rule applies.
TEST_DEM_SPEC = SyntheticDemSpec(
    width=160,
    height=160,
    resolution_m=50.0,
    origin_x_m=400_000.0,
    origin_y_m=4_500_000.0,
    crs="EPSG:25830",
    seed=7,
)


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """Guarantee no cached settings or engine leaks between tests."""
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    return directory


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(
        environment=Environment.CI,
        data_dir=data_dir,
        database_url=None,
        log_json=True,
    )


@pytest.fixture
def app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.storage.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# --- Raster fixtures ---------------------------------------------------------


@pytest.fixture
def metric_dem(tmp_path: Path) -> Path:
    """A synthetic DEM in EPSG:25830, the shape a real upload should have."""
    path = tmp_path / "dem_25830.tif"
    write_synthetic_dem(path, TEST_DEM_SPEC)
    return path


@pytest.fixture
def study_area(metric_dem: Path) -> StudyArea:
    """A study area covering the middle of ``metric_dem``.

    Derived from the raster's own bounds so the two always line up, whatever
    the spec says.
    """
    from shapely.geometry import box

    from app.geo.area import reproject_geometry

    with rasterio.open(metric_dem) as dataset:
        left, bottom, right, top = dataset.bounds
        crs = dataset.crs.to_string()

    inset_x = (right - left) * 0.25
    inset_y = (top - bottom) * 0.25
    inner = box(left + inset_x, bottom + inset_y, right - inset_x, top - inset_y)
    wgs84 = reproject_geometry(inner, crs, "EPSG:4326")

    from shapely.geometry import mapping

    return parse_study_area(dict(mapping(wgs84)))


@pytest.fixture
def geographic_dem(tmp_path: Path) -> Path:
    """A DEM in EPSG:4326: valid input, but it must be reprojected before use."""
    path = tmp_path / "dem_4326.tif"
    width, height = 120, 120
    resolution_deg = 0.001
    rng = np.random.default_rng(11)
    elevation = (
        600.0
        + 200.0 * np.sin(np.linspace(0.0, 3.0, width))[None, :]
        + 150.0 * np.cos(np.linspace(0.0, 3.0, height))[:, None]
        + rng.normal(0.0, 5.0, size=(height, width))
    ).astype(np.float32)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-3.75, 40.45, resolution_deg, resolution_deg),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)
    return path


@pytest.fixture
def dem_without_crs(tmp_path: Path) -> Path:
    """A GeoTIFF with no georeferencing at all. Must always be rejected."""
    path = tmp_path / "no_crs.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=32, height=32, count=1, dtype="float32"
    ) as dataset:
        dataset.write(np.full((32, 32), 500.0, dtype=np.float32), 1)
    return path


# --- Database fixtures -------------------------------------------------------

TEST_DATABASE_URL_ENV = "SENTINEL_TEST_DATABASE_URL"
DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel_test"


def _test_database_url() -> str:
    return os.environ.get(TEST_DATABASE_URL_ENV) or os.environ.get(
        "SENTINEL_DATABASE_URL", DEFAULT_TEST_DATABASE_URL
    )


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    """A PostGIS engine, or skip the test when no database is reachable.

    Schema comes from ``Base.metadata``, not from migrations, so the tests stay
    fast; CI runs ``alembic upgrade head`` separately to prove the migrations
    themselves work.
    """
    from app.db import models  # noqa: F401 - registers the entities
    from app.db.base import Base

    url = _test_database_url()
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            connection.commit()
    except Exception as error:  # noqa: BLE001 - any failure means "no database here"
        pytest.skip(f"No PostGIS database at {url}: {error}")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(database_engine: Engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back."""
    connection = database_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def api_client(
    settings: Settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A client whose requests all share the rolled-back test session."""
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.storage.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    from app.api.deps import db_session as db_session_dependency
    from app.api.deps import settings_dependency

    application = create_app(settings)

    def _session_override() -> Iterator[Session]:
        # The outer transaction is rolled back by the db_session fixture, so
        # the handler's commit only ends its nested transaction.
        yield db_session

    application.dependency_overrides[db_session_dependency] = _session_override
    application.dependency_overrides[settings_dependency] = lambda: settings

    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()


@pytest.fixture
def madrid_area_geojson() -> dict[str, Any]:
    """A ~100 km² study area near Madrid, in EPSG:4326."""
    return {
        "type": "Polygon",
        "coordinates": [
            [[-3.80, 40.35], [-3.68, 40.35], [-3.68, 40.44], [-3.80, 40.44], [-3.80, 40.35]]
        ],
    }
