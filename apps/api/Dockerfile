# Sentinel Planner API.
# Build context: apps/api
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /srv/api

# The rasterio wheel bundles GDAL but still links against a few system
# libraries that the slim image does not ship.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libexpat1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: the layer is reused while only application code changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# Data lives on a volume; the image never bundles datasets.
ENV SENTINEL_DATA_DIR=/srv/data
RUN mkdir -p /srv/data

EXPOSE 8000

# --- Development: reloads on change, dev dependencies installed ---------------
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- Production ---------------------------------------------------------------
FROM base AS prod
RUN groupadd --system sentinel && useradd --system --gid sentinel sentinel \
    && chown -R sentinel:sentinel /srv
USER sentinel
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
