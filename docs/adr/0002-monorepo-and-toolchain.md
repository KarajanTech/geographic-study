# ADR 0002: Monorepo, toolchain and service boundaries

- Status: accepted
- Date: 2026-07-25
- Phase: 0

## Context

Phase 0 must give a new contributor a project that starts, tests and lints in
one command, without prescribing the geospatial design that later phases will
settle.

## Decision

**One repository, two applications.** `apps/api` (FastAPI, Python 3.12) and
`apps/web` (Next.js, TypeScript) with a shared `packages/shared-schemas`. No
microservices: `ARCHITECTURE.md` calls for services as modules inside one API
process, and heavy work moves to worker tasks when Phase 3 needs it, not before.

**uv for Python, npm workspaces for Node.** Both are lock-file based, so CI and
a laptop resolve the same versions. `uv.lock` and `package-lock.json` are
committed.

**The OpenAPI document is the API/frontend contract.** `scripts/export_openapi.py`
writes `packages/shared-schemas/openapi.json`; `openapi-typescript` generates
the TypeScript types from it. CI fails when the committed artefacts drift. This
is what keeps "typed API client" from decaying into hand-maintained duplicates.

**Configuration comes from the environment only.** `pydantic-settings` with the
`SENTINEL_` prefix, a git-ignored `.env`, and a committed `.env.example`. The
repository root is discovered from marker files, so no path is hardcoded to a
machine.

**Structured logging from day one.** structlog, JSON outside local development,
one request-id bound per HTTP request. Analysis runs must be reconstructable
from logs.

**PostGIS via Docker Compose, migrations via Alembic.** The first migration only
enables the PostGIS extension; entities arrive with Phase 1. Compose is the
single way to get a database, so nobody depends on a hand-made local instance.

**Rasterio wheels instead of a system GDAL.** Contributors do not need GDAL
installed. When Phase 3 needs `gdal_viewshed`, it goes behind the
`ViewshedEngine` interface, which is where a system GDAL or an alternative
implementation can be swapped in.

## Alternatives considered

- **Separate repositories per app** — rejected: the API/frontend contract would
  need versioned releases before there is anything to release.
- **Poetry / plain pip-tools** — rejected: uv is faster and already resolves and
  locks both the project and its dev tooling in one file.
- **Hand-written TypeScript types** — rejected: they drift silently, and a drift
  in a coverage payload is a wrong number on screen.
- **A system GDAL requirement in Phase 0** — rejected: it blocks onboarding for
  a capability nothing uses until Phase 3.

## Consequences

- `make install && make dev` is the whole setup.
- Changing an API schema without running `make schemas` fails CI, on purpose.
- Adding a worker queue later touches Compose and `app/workers`, not the layout.
